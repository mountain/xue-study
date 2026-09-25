use adva_lisp::{compile_function, evaluate_finite, import_diagram_json, link_modules, parse_module};
use serde_json::{Value, json};
use std::{collections::BTreeMap, env, fs, io::Write};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().collect();
    if args.len() != 4 {
        return Err("usage: sphaera-frame-probe SOURCE REQUEST FRESH_OUTPUT".into());
    }
    let source = fs::read_to_string(&args[1])?;
    let request: Value = serde_json::from_str(&fs::read_to_string(&args[2])?)?;
    let linked = link_modules(vec![parse_module(&source)?])?;
    let mut compiled = BTreeMap::new();
    let mut artifacts = BTreeMap::new();
    let names = request["functions"].as_array().ok_or("missing functions")?;
    if names.len() > 16 {
        return Err("function budget exceeded".into());
    }
    for name in names {
        let name = name.as_str().ok_or("invalid function")?;
        let artifact = compile_function(&linked, "spectrum-frame", name)?;
        if !artifact.certificate.certified() || !artifact.graft_trace.certificate.certified() {
            return Err("native compilation or graft certificate incomplete".into());
        }
        let restored = import_diagram_json(&artifact.result.to_json()?)?;
        if !restored.certificate.certified() || restored.result != artifact.result {
            return Err("checked import differs from compiled diagram".into());
        }
        artifacts.insert(name.to_owned(), json!({
            "compilation": artifact,
            "checked_import_certificate": restored.certificate
        }));
        compiled.insert(name.to_owned(), artifact);
    }
    let cases = request["cases"].as_array().ok_or("missing cases")?;
    if cases.len() > 512 {
        return Err("evaluation budget exceeded".into());
    }
    let mut evaluations = Vec::new();
    for case in cases {
        let name = case["function"].as_str().ok_or("missing case function")?;
        let inputs: BTreeMap<String, f64> = serde_json::from_value(case["inputs"].clone())?;
        let artifact = compiled.get(name).ok_or("function was not compiled")?;
        let result = evaluate_finite(&artifact.result, &inputs)?;
        evaluations.push(json!({"id": case["id"], "function": name, "result": result}));
    }
    let invalid = link_modules(vec![parse_module(
        "(module bad (export f) (def f (fn ((x Real)) Real (add (use x) (use x)))))",
    )?])?;
    let alias_refusal = compile_function(&invalid, "bad", "f")
        .expect_err("implicit alias control must be refused")
        .to_string();
    let nan_refusal = evaluate_finite(
        &compiled["turn-i"].result,
        &BTreeMap::from([("e".to_owned(), f64::NAN), ("o".to_owned(), 1.0)]),
    ).expect_err("nonfinite input control must be refused").to_string();
    let output = json!({
        "status": "NativeCompilationAndFiniteEvaluationCompleted",
        "functions": artifacts,
        "evaluations": evaluations,
        "refusals": {"implicit_alias": alias_refusal, "nonfinite_input": nan_refusal},
        "boundary": "Native GraftFrame and checked Real arithmetic; no new native complex Frame type, weather dynamics or forecast-skill certificate."
    });
    let bytes = serde_json::to_vec_pretty(&output)?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("native evidence size budget exceeded".into());
    }
    let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&args[3])?;
    file.write_all(&bytes)?;
    println!("native functions={}, evaluations={}, bytes={}", compiled.len(), cases.len(), bytes.len());
    Ok(())
}
