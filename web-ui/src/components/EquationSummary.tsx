import katex from "katex";
import type { AesResult, ExpressionSpec, PDEProblemSpec } from "../types";

type Props = {
  aesResult?: AesResult;
  status: string;
};

export function EquationSummary({ aesResult, status }: Props) {
  const spec = aesResult?.pde_spec;
  const formulas = spec ? typedFormulas(spec, aesResult) : fallbackFormulas(aesResult);

  return (
    <header className="equationSummary">
      <div className="equationHeading">
        <div>
          <span className="equationEyebrow">Solved formulation</span>
          <h2>{titleFor(aesResult?.pde_info)}</h2>
        </div>
        <div className="statusBadge">{status}</div>
      </div>
      <div className="equationContent">
        {formulas.map((formula) => (
          <MathLine source={formula} key={formula} />
        ))}
      </div>
      <p className="equationMeta">
        Status: <strong>{aesResult?.agent_status || "unknown"}</strong>
        <span>Next: <strong>{aesResult?.next_action || "unknown"}</strong></span>
      </p>
    </header>
  );
}

function MathLine({ source }: { source: string }) {
  const html = katex.renderToString(source, {
    displayMode: true,
    throwOnError: false,
    strict: "warn",
    trust: false,
  });
  return <div className="mathLine" dangerouslySetInnerHTML={{ __html: html }} />;
}

function typedFormulas(spec: PDEProblemSpec, result?: AesResult) {
  const unknown = latexIdentifier(spec.equation.unknown || "u");
  const diffusion = expressionLatex(spec.equation.diffusion);
  const source = expressionLatex(spec.equation.source);
  const dimension = spec.spatial_dimension;
  const formulas = [domainFormula(result?.domain_info, dimension)];

  if (spec.equation.family === "transient_diffusion") {
    formulas.push(
      `\\frac{\\partial ${unknown}}{\\partial t}-\\nabla\\!\\cdot\\!\\left(${diffusion}\\nabla ${unknown}\\right)=${source}`,
    );
  } else if (spec.equation.family === "stationary_diffusion") {
    formulas.push(`-\\nabla\\!\\cdot\\!\\left(${diffusion}\\nabla ${unknown}\\right)=${source}`);
  } else {
    formulas.push(`\\text{${latexText(spec.equation.strong_form)}}`);
  }

  for (const condition of spec.boundary_conditions || []) {
    const value = expressionLatex(condition.value);
    const region = latexText(condition.region);
    if (condition.type === "dirichlet") {
      formulas.push(`${unknown}=${value}\\quad\\text{on }\\Gamma_{\\mathrm{${region}}}`);
    } else if (condition.type === "neumann") {
      formulas.push(`-${diffusion}\\nabla ${unknown}\\cdot\\mathbf n=${value}\\quad\\text{on }\\Gamma_{\\mathrm{${region}}}`);
    } else {
      formulas.push(`\\mathcal B(${unknown})=${value}\\quad\\text{on }\\Gamma_{\\mathrm{${region}}}`);
    }
  }

  if (spec.initial_condition?.value) {
    const t0 = spec.time?.t0 ?? 0;
    formulas.push(`${unknown}(\\mathbf x,${formatNumber(t0)})=${expressionLatex(spec.initial_condition.value)}`);
  }
  if (spec.time) {
    formulas.push(
      `t\\in[${formatNumber(spec.time.t0)},${formatNumber(spec.time.t_end)}],\\qquad \\Delta t=${formatNumber(spec.time.dt)},\\qquad\\text{${latexText(spec.time.scheme.replace(/_/g, " "))}}`,
    );
  }
  return formulas;
}

function fallbackFormulas(result?: AesResult) {
  const dimension = result?.domain_info === "unit_cube" ? 3 : 2;
  const diffusion = expressionLatex({ kind: "symbolic", value: result?.coefficient_info || "a" });
  const source = expressionLatex({ kind: "symbolic", value: result?.source_info || "f" });
  const transient = String(result?.pde_info || "").includes("time_dependent");
  const formulas = [domainFormula(result?.domain_info, dimension)];
  formulas.push(
    transient
      ? `\\frac{\\partial u}{\\partial t}-\\nabla\\cdot(${diffusion}\\nabla u)=${source}`
      : `-\\nabla\\cdot(${diffusion}\\nabla u)=${source}`,
  );
  if (result?.bc_info) {
    formulas.push(`\\text{Boundary conditions: ${latexText(result.bc_info.replace(/_/g, " "))}}`);
  }
  if (result?.initial_condition_info && !result.initial_condition_info.startsWith("unknown_")) {
    formulas.push(`u(\\mathbf x,0)=${expressionTextLatex(result.initial_condition_info)}`);
  }
  return formulas;
}

function domainFormula(domain: string | undefined, dimension: number) {
  if (domain === "unit_square") {
    return "\\Omega=[0,1]^2\\subset\\mathbb R^2";
  }
  return `\\Omega\\subset\\mathbb R^{${dimension}}\\quad\\text{${latexText((domain || "computational domain").replace(/_/g, " "))}}`;
}

function expressionLatex(expression: ExpressionSpec) {
  return expressionTextLatex(expression?.value || "0");
}

function expressionTextLatex(value: string) {
  return String(value)
    .replace(/\\/g, "")
    .replace(/\bpi\b/gi, "\\pi")
    .replace(/\bsin\s*\(/gi, "\\sin(")
    .replace(/\bcos\s*\(/gi, "\\cos(")
    .replace(/\bexp\s*\(/gi, "\\exp(")
    .replace(/([A-Za-z0-9)]+)\*\*([A-Za-z0-9.+-]+)/g, "$1^{$2}")
    .replace(/\*/g, "\\,");
}

function latexIdentifier(value: string) {
  return /^[A-Za-z]+$/.test(value) ? value : "u";
}

function latexText(value: string) {
  return String(value).replace(/[{}\\]/g, "").replace(/_/g, " ");
}

function formatNumber(value: number) {
  return Number.isFinite(value) ? String(value) : "0";
}

function titleFor(value?: string) {
  return (value || "AES numerical problem")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}
