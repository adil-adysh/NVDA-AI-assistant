import path from "node:path";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [svelte()],
	base: "./",
	build: {
		target: "es2020",
		outDir: "assets",
		emptyOutDir: false,
		cssCodeSplit: false,
		lib: {
			entry: path.resolve(__dirname, "webui/src/main.js"),
			formats: ["iife"],
			name: "NvdaUiHostWebUi",
			fileName: () => "host.js",
		},
		rollupOptions: {
			output: {
				assetFileNames: (assetInfo) => {
					if (assetInfo.name && assetInfo.name.endsWith(".css")) {
						return "host.css";
					}
					return "[name][extname]";
				},
			},
		},
	},
});
