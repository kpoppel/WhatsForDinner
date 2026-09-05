import { build } from "esbuild";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const outputDirectory = resolve(root, "app/static/dist");

await rm(outputDirectory, { force: true, recursive: true });
await mkdir(outputDirectory, { recursive: true });

const buildResult = await build({
  bundle: true,
  entryNames: "client-[hash]",
  entryPoints: [resolve(root, "app/static/client.js")],
  format: "esm",
  metafile: true,
  minify: true,
  outdir: outputDirectory,
  sourcemap: false,
  write: true,
});

const files = Object.keys(buildResult.metafile.outputs)
  .filter((output) => output.endsWith(".js") || output.endsWith(".css"))
  .map((output) => `/static/dist/${output.split("/").at(-1)}`);
const appJs = files.find((file) => file.endsWith(".js"));
const appCss = files.find((file) => file.endsWith(".css"));

if (!appJs || !appCss) {
  throw new Error("Client build did not produce both JavaScript and CSS assets.");
}

const buildIdMatch = appJs.match(/client-([A-Z0-9]+)\.js$/i);
if (!buildIdMatch) {
  throw new Error("Could not determine the client build identifier.");
}

await writeFile(
  resolve(outputDirectory, "manifest.json"),
  `${JSON.stringify({ app_css: appCss, app_js: appJs, assets: files, build_id: buildIdMatch[1] }, null, 2)}\n`,
);