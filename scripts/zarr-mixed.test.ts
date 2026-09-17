/**
 * A store whose two arrays differ in their inner codec chain.
 *
 * `zarr.test.ts` covers a store written whole on one chain (`wind10m.zarr`)
 * and a store written whole on the other (`tmp2m.delta.zarr`). Neither is
 * what `export_bundle(delta="auto")` writes: that decides per array, from
 * the measurement in `zarrstore._delta_wins`, so one store can hold a
 * differenced array beside a plain one.
 *
 * The claim under test is that this plays. `zarr/session.ts` reads each
 * array's own `zarr.json` for its chain, and its "every array of a store
 * must be cut the same way" check compares the tiling and the time chunk
 * rather than the codecs — so the mixed store should assemble byte for byte
 * as the container decodes the same bundle.
 *
 * `tests/prepare_mixed_fixture.py` builds the store; a fresh checkout runs
 * it the way `zarr.test.ts` runs its own fixture generator.
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { ZarrSession } from "../../web/src/zarr/session";
import { ZarrStore } from "../../web/src/zarr/store";
import { localFetch, newFetchLog } from "../../web/tooling/localfetch";

function repositoryRoot(): string {
  let directory = process.cwd();
  while (!existsSync(join(directory, "pyproject.toml"))) {
    const parent = dirname(directory);
    if (parent === directory) throw new Error("repository root not found from the working directory");
    directory = parent;
  }
  return directory;
}

const REPOSITORY_ROOT = repositoryRoot();
const FIXTURE_ROOT = join(REPOSITORY_ROOT, "tests/fixtures/generated/web");
const WASM_DIR = join(REPOSITORY_ROOT, "web/src/wasm/");
/** One array on each chain; the store's group document names both. */
const MIXED_STORE = "wind10m.mixed.zarr";
const BUNDLE = "wind10m.xue";
const DIFFERENCED = "vgrd10m";
const PLAIN = "ugrd10m";

type Wasm = typeof import("../../web/src/wasm/xue");
let wasm: Wasm;

function ensureFixtures(): void {
  if (existsSync(`${FIXTURE_ROOT}/${MIXED_STORE}/zarr.json`)) return;
  const python = process.env.PYTHON || ".venv/bin/python";
  // The bundle and the standard store come first: this fixture is derived
  // from them, not generated from scratch.
  for (const script of ["tests/prepare_web_fixture.py", "tests/prepare_mixed_fixture.py"]) {
    const result = spawnSync(python, [script], { cwd: REPOSITORY_ROOT, encoding: "utf8" });
    if (result.status !== 0) {
      throw new Error(`${script} failed (${python}): ${result.error?.message ?? result.stderr ?? result.stdout}`);
    }
  }
}

beforeAll(async () => {
  ensureFixtures();
  wasm = await import("../../web/src/wasm/xue");
  await wasm.default({ module_or_path: readFileSync(`${WASM_DIR}xue_bg.wasm`) });
}, 300_000);

function chainOf(name: string): string[] {
  const document = JSON.parse(readFileSync(`${FIXTURE_ROOT}/${MIXED_STORE}/${name}/zarr.json`, "utf8"));
  const codecs = document.codecs ?? [];
  if (codecs[0]?.name === "sharding_indexed") {
    return codecs[0].configuration.codecs.map((codec: { name: string }) => codec.name);
  }
  return codecs.map((codec: { name: string }) => codec.name);
}

/** The store and the session over it, in the fixture directory. */
async function openMixed() {
  const store = new ZarrStore(`local://${MIXED_STORE}`, "deadbeef", {
    fetch: localFetch(FIXTURE_ROOT, newFetchLog()),
  });
  return ZarrSession.open(store, wasm.decodeChunk);
}

describe("a store whose arrays use different codec chains", () => {
  it("really does hold one array of each chain", () => {
    expect(chainOf(DIFFERENCED)).toEqual(["xue.delta", "bytes", "zstd"]);
    expect(chainOf(PLAIN)).toEqual(["bytes", "zstd"]);
  });

  it("opens, and keeps a layout per array", async () => {
    const session = await openMixed();
    expect(session.numericIds).toEqual([1, 2]);
  });

  it("assembles every frame of both arrays as the container decodes them", async () => {
    const session = await openMixed();
    const bundle = new wasm.WasmBundle(readFileSync(`${FIXTURE_ROOT}/${BUNDLE}`));
    const frameCount = JSON.parse(bundle.metadataJson()).time.frameCount as number;

    // The chunk boundary at 6, a frame inside a chunk, and the last frame of
    // the axis — the one whose time chunk is padded.
    const offsets = [0, 1, 5, 6, 7, frameCount - 2, frameCount - 1];
    for (const numericId of [1, 2]) {
      for (const offset of offsets) {
        const assembled = await session.decodeFrame(numericId, offset);
        expect(Buffer.from(assembled)).toEqual(Buffer.from(bundle.decodeFrame(numericId, offset)));
      }
    }
  });

  it("reads a cell's series through both chains", async () => {
    const session = await openMixed();
    const bundle = new wasm.WasmBundle(readFileSync(`${FIXTURE_ROOT}/${BUNDLE}`));
    const { width, height } = JSON.parse(session.metadataJson).grid;

    for (const numericId of [1, 2]) {
      for (const [column, row] of [
        [0, 0],
        [10, 4],
        [width - 1, height - 1],
      ] as const) {
        const series = await session.decodeSeries(numericId, column, row);
        expect(Buffer.from(series)).toEqual(Buffer.from(bundle.decodeSeries(numericId, column, row)));
      }
    }
  });
});
