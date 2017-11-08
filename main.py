"""Main module of kytos/mef_eline Kytos Network Application.

NApp to provision circuits from user request
"""
import json
import os
import requests
import pickle

from pathlib import Path
from flask import abort, request, jsonify

from kytos.core import KytosNApp, log, rest
from napps.kytos.mef_eline import settings
from napps.kytos.mef_eline.models import Circuit, Endpoint


class Main(KytosNApp):
    """Main class of amlight/mef_eline NApp.

    This class is the entry point for this napp.
    """

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        pass

    def execute(self):
        """This method is executed right after the setup method execution.

        You can also use this method in loop mode if you add to the above setup
        method a line like the following example:

            self.execute_as_loop(30)  # 30-second interval.
        """
        pass

    def shutdown(self):
        """This method is executed when your napp is unloaded.

        If you have some cleanup procedure, insert it here.
        """
        pass

    def save_circuit(self, circuit):
        save_path = Path(__file__).parent / settings.CIRCUITS_PATH
        save_path.mkdir(exist_ok=True)
        if not os.access(save_path, os.W_OK):
            log.error("Could not save circuit on %s", save_path)
            return False

        output = os.path.join(save_path, circuit.id)
        with open(output, 'wb') as fp:
            fp.write(pickle.dumps(circuit))

        return True

    def load_circuit(self, circuit_id):
        path = os.path.join(settings.CIRCUITS_PATH, circuit_id)
        if not os.access(path, os.R_OK):
            log.error("Could not load circuit from %s", path)
            return None

        with open(path, 'rb') as fp:
            return pickle.load(fp)

    def load_circuits(self):
        result = []
        for (dirpath, dirnames, filenames) in os.walk(settings.CIRCUITS_PATH):
            for filename in filenames:
                result.append(self.load_circuit(filename))
        return result

    def remove_circuit(self, circuit_id):
        path = os.path.join(settings.CIRCUITS_PATH, circuit_id)
        if not os.access(path, os.W_OK):
            log.error("Could not delete circuit from %s", path)
            return None

        os.remove(path)

    def get_paths(self, circuit):
        endpoint = "%s%s:%s/%s:%s" % (settings.PATHFINDER_URL,
                                      circuit.uni_a.dpid,
                                      circuit.uni_a.port,
                                      circuit.uni_z.dpid,
                                      circuit.uni_z.port)
        request = requests.get(endpoint)
        if request.status_code != requests.codes.ok:
            log.error("Failed to get paths at %s. Returned %s",
                      endpoint,
                      request.status_code)
            return None
        data = request.json()
        return data.get('paths')

    @staticmethod
    def install_flow(dpid, in_port, out_port, vlan_id):
        endpoint = "%sflows/%s" % (settings.MANAGER_URL, dpid)
        data = [{"match": {"in_port": int(in_port), "dl_vlan": vlan_id},
                "actions": [{"action_type": "output", "port": int(out_port)}]}]
        requests.post(endpoint, json=data)

    def install_flows_for_circuit(self, circuit):
        vlan_id = circuit.uni_a.tag.value
        for end_a, end_b in zip(circuit.path[:-1], circuit.path[1:]):
            if end_a.dpid == end_b.dpid:
                self.install_flow(end_a.dpid, end_a.port, end_b.port, vlan_id)
                self.install_flow(end_a.dpid, end_b.port, end_a.port, vlan_id)

    @rest('/circuits', methods=['GET'])
    def get_circuits(self):
        circuits = {}
        for circuit in self.load_circuits():
            circuits[circuit.id] = circuit.as_dict()

        return jsonify({'circuits': circuits}), 200

    @rest('/circuits/<circuit_id>', methods=['GET'])
    def get_circuit(self, circuit_id):
        circuit = self.load_circuit(circuit_id)
        if not circuit:
            return jsonify({"error": "Circuit not found"}), 404

        return jsonify(circuit.as_dict()), 200

    @rest('/circuits', methods=['POST'])
    def create_circuit(self):
        """
        Receive a user request to create a new circuit, find a path for the
        circuit, install the necessary flows and stores the information about
        it.
        """
        # TODO: Check if circuit already exists
        data = request.get_json()

        try:
            circuit = Circuit.from_dict(data)
        except Exception as e:
            return json.dumps({'error': e}), 400

        paths = self.get_paths(circuit)
        if not paths:
            error = "Pathfinder returned no path for this circuit."
            log.error(error)
            return jsonify({"error": error}), 503

        # Select best path
        path = paths[0]['hops']

        # We do not need backup path, because we need to implement a more
        # suitable way to reconstruct paths

        for endpoint in path:
            dpid = endpoint[:23]
            if len(endpoint) > 23:
                port = endpoint[24:]
                endpoint = Endpoint(dpid, port)
                circuit.add_endpoint_to_path(endpoint)

        # Save circuit to disk
        self.save_circuit(circuit)

        self.install_flows_for_circuit(circuit)

        return jsonify(circuit.as_dict()), 201

    @rest('/circuits/<circuit_id>', methods=['DELETE'])
    def delete_circuit(self, circuit_id):
        try:
            self.remove_circuit(circuit_id)
        except Exception as e:
            return jsonify({"error": e}), 503

        return jsonify({"success": "Circuit deleted"}), 200

    #@rest('/circuits/<circuit_id>', methods=['PATCH'])
    #def update_circuit(self, circuit_id):
    #    pass

    #@rest('/circuits/byLink/<link_id>')
    #def circuits_by_link(self, link_id):
    #    pass

    #@rest('/circuits/byUNI/<dpid>/<port>')
    #def circuits_by_uni(self, dpid, port):
    #    pass
