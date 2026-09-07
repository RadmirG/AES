# AES Standard Geometry Examples

This directory contains versioned, reusable geometry inputs for the AES
meshing and visualization workflow. Each example has two equivalent files:

- `geometry.yaml` is the human-authored representation.
- `geometry.json` is the normalized browser/runtime representation.

Both files conform to the AES `GeometrySpec` 1.0 contract. Automated tests
validate both representations and require them to remain structurally equal.

The 3D plate examples are solid volumes with a finite thickness. They are not
shell or plate finite-element models.

| Example | Dimension | Construction | Named boundaries |
| --- | ---: | --- | --- |
| `unit-square-2d` | 2 | rectangle | `x_min`, `x_max`, `y_min`, `y_max` |
| `square-with-hole-2d` | 2 | rectangle minus disk | outer edges, `hole_wall` |
| `unit-plate-solid-3d` | 3 | box | six exterior faces |
| `plate-with-hole-solid-3d` | 3 | box minus through-cylinder | exterior faces, `hole_wall` |
| `l-shaped-domain-2d` | 2 | rectangle minus corner rectangle | six named edge segments and aggregate `boundary` |
| `annulus-2d` | 2 | disk minus concentric disk | `inner_wall`, `outer_wall`, aggregate `boundary` |
| `channel-with-cylinder-2d` | 2 | channel rectangle minus disk | `inlet`, `outlet`, walls, `obstacle_wall` |
| `stepped-bracket-solid-3d` | 3 | joined boxes minus two cylinders | mounting holes, `base_bottom`, `top_load` |
| `finned-heat-sink-solid-3d` | 3 | joined base and five fin boxes | `base_bottom`, aggregate `boundary` |

Boundary names describe geometry. Simulation roles such as `inlet`, `outlet`,
`wall`, `load`, or `Dirichlet boundary` belong to a PDE/scenario definition
and should reference these stable names.

The first four geometries are compact baseline fixtures. The remaining five
exercise re-entrant corners, curved cavities, flow boundaries, sequential CSG,
multiple holes, thin features, and multi-body fusion. The Workbench builds a
bounded browser preview for selection; Gmsh/OpenCASCADE remains authoritative
for the numerical mesh.
