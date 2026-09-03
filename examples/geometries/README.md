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

Boundary names describe geometry. Simulation roles such as `inlet`, `outlet`,
`wall`, `load`, or `Dirichlet boundary` belong to a PDE/scenario definition
and should reference these stable names.

