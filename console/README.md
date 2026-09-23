# Atlas console

The React front end for Atlas: the landing page served at `/` and the query
console served at `/app`. Vite multi-page build (`index.html` → console,
`landing.html` → landing), Tailwind v4, shadcn/ui primitives, Motion for
anything that has to interpolate.

`npm run build` writes straight into `../src/atlas/api/static/`, and that
output **is committed**. The Python image stays Node-free that way: FastAPI
mounts the built files and the Dockerfile never installs a toolchain. The
consequence is that a source change is not deployed until the build has been
re-run and the new hashed assets committed — the served bundle name is the
thing to check when a change appears to have had no effect.

```bash
npm install
npm run dev      # standalone, expects the API on :8010
npm run build    # writes ../src/atlas/api/static/ — commit the result
```

Design direction and the vocabulary behind it are in `../DESIGN.md`.
