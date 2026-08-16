# CityGen report

The report lives in **[`report.html`](report.html)**, which carries the figures,
the pipeline diagram and the self assessment. Open it in a browser.

At a glance, for the `nyc_midtown` area (Midtown Manhattan, bbox
`40.7500, -73.9860, 40.7555, -73.9790`, 611 x 591 m):

| | |
|---|---|
| scene | 2,811 nodes: 2,294 extrude (1,648 building volumes + 646 curb prisms), 344 mesh, 173 ribbon |
| heights | 97.6% from a stated `height` tag |
| roads | 173 carriageways, 18.7 km, 17 widths from the tagged cross section, 87 junctions resolved |
| ground | 143 ground cover surfaces; 3 below grade station buildings excluded |
| checks | verifier ok, 0 errors, 0 warnings; worst vertex 0.7 cm; bearing delta 0.5 deg |
| output | byte identical across runs, sha256 `cf282190` |

Reproduce:

```bash
python3 agent_scripts/nyc_midtown/pipeline.py --area nyc_midtown --verify
tools/verify_area.sh nyc_midtown
tools/stage_area.sh nyc_midtown
```
