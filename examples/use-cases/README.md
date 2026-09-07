# AES PDE Use-Case Catalog

`catalog.yaml` turns the PDE survey into an explicit AES capability catalog.
Each entry contains a representative equation, applications, an executable-style
prompt, a recommended geometry, and the numerical capabilities that are needed.

The support status is deliberately conservative:

| Status | Meaning |
| --- | --- |
| `immediate` | The production typed DOLFINx compiler can validate, compile, execute, and visualize the case now. |
| `compiler_extension` | The problem fits the current FEM architecture, but its typed operators, weak form, or solver path must be implemented. |
| `advanced_backend` | The problem needs a substantial new discretization or backend contract. |

## Current Coverage

| No. | PDE family | Status | Principal missing capability |
| ---: | --- | --- | --- |
| 1 | Laplace | immediate | none for constant Dirichlet data |
| 2 | Poisson | immediate | none for constant scalar data |
| 3 | Helmholtz | compiler extension | reaction term and indefinite solver |
| 4 | Linear elasticity | compiler extension | vector/tensor formulation |
| 5 | Stationary reaction-convection-diffusion | compiler extension | advection, reaction, stabilization |
| 6 | Semilinear elliptic | compiler extension | nonlinear residual and Jacobian |
| 7 | p-Laplace | compiler extension | gradient-dependent nonlinearity |
| 8 | Monge-Ampere | advanced backend | fully nonlinear Hessian method |
| 9 | Heat | immediate | none for constant scalar data |
| 10 | Transient reaction-convection-diffusion | compiler extension | transient advection/reaction |
| 11 | Fisher-KPP | compiler extension | nonlinear reaction |
| 12 | Allen-Cahn | compiler extension | nonlinear potential and time solve |
| 13 | Viscous Burgers | compiler extension | nonlinear convection and 1D geometry |
| 14 | Porous medium | compiler extension | degenerate nonlinear diffusion |
| 15 | Cahn-Hilliard | advanced backend | mixed fourth-order formulation |
| 16 | Incompressible Navier-Stokes | advanced backend | mixed velocity-pressure CFD |
| 17 | Wave | compiler extension | second-order time integration |
| 18 | Linear transport | compiler extension | upwind or stabilized advection |
| 19 | Maxwell | advanced backend | H-curl vector elements |
| 20 | Inviscid Burgers | advanced backend | conservative shock-capturing method |
| 21 | Euler | advanced backend | compressible conservation-law backend |
| 22 | Shallow water | advanced backend | positivity-preserving coupled solver |
| 23 | Schrodinger | advanced backend | complex fields and unitary integration |
| 24 | Hamilton-Jacobi/Eikonal | advanced backend | monotone viscosity-solution method |

Entries 1, 2, and 9 include complete `PDEProblemSpec` 2.0 documents. Tests
validate those specifications against their referenced `GeometrySpec` and the
current compiler capability plan. An `immediate` label therefore represents a
checked software contract, not only a documentation claim.
