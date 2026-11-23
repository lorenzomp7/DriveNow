"""What the DriveNow cars tell about the lights they approach, for ``probe.ProbeLearner``.

Shared by the SUMO worlds whose lights have no open timing data (``hamburg/world.py``
for the lights outside Hamburg's feed, ``wzdx_world.py`` for the US work zones). The
world sets ``self.probe`` (a ProbeLearner), ``self._probe_edges`` (the approaches to
learn) and ``self._probe_prev`` (an empty dict), and calls ``_report_probes`` each step.
"""

from __future__ import annotations


class ProbeReports:
    def _report_probes(self) -> None:
        """What each DriveNow car tells about the light ahead: waiting, driving off, crossing."""
        for vid, veh in self.vehicles.items():
            if not veh.equipped or not veh.route:
                continue
            edge, inside = veh.edge, vid in self._internal
            prev = self._probe_prev.get(vid)
            if prev is not None and prev[0] in self._probe_edges and not prev[1] and (inside or edge != prev[0]):
                self.probe.report(self.t, vid, prev[0], 0.0, veh.v, crossed=True)
            if edge in self._probe_edges and not inside:
                to_line = self.net.edges[edge].length - veh.pos
                self.probe.report(self.t, vid, edge, to_line, veh.v, crossed=False)
            self._probe_prev[vid] = (edge, inside)
        if len(self._probe_prev) > len(self.vehicles) + 200:
            for vid in [v for v in self._probe_prev if v not in self.vehicles]:
                del self._probe_prev[vid]
                self.probe.forget(vid)
