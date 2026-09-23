# atlas.hulage.in → Cloud Run

Cloud Run does not offer domain mappings in `asia-south1` (`501 Creating domain
mappings is not allowed in asia-south1`), and moving the service to a region
that does would put every Indian request across an ocean. So the domain is
fronted the same way Finertia is: a Vercel project that rewrites every path to
the service URL, terminating TLS at the edge and adding one hop of ~20–40 ms.

Nothing is built here. `vercel.json` is the whole project: no framework, no
output directory, one catch-all rewrite. The API serves the landing page, the
console and the OpenAPI docs itself, so there is no split between static and
proxied paths — unlike Finertia, where Vercel hosts the SPA.

## Deploy

```bash
cd proxy
vercel link        # once: scope hulagerushikesh, project atlas
vercel --prod
vercel domains add atlas.hulage.in     # then add the CNAME it prints, at Cloudflare
```

Cloudflare holds DNS for `hulage.in`. The record Vercel asks for is a CNAME on
`atlas` pointing at its `*.vercel-dns-*.com` target; leave Cloudflare's proxy
**off** (grey cloud) so Vercel can issue the certificate.

## When the service URL changes

The destination is pinned to the current Cloud Run URL. A new *revision* keeps
that URL; deleting and recreating the *service* would not, so update the
rewrite if that ever happens.
