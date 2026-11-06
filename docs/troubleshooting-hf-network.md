# Hugging Face downloads fail before the inference API starts

A systemd service can be running while model initialization is still in
progress. Check the configured service logs when `/health` refuses connections.
`LocalEntryNotFoundError` can wrap an earlier network error; inspect that error
before changing authentication or reinstalling model packages.

## Diagnose DNS in the service context

Compare the actual model's small configuration URL using a HEAD request, with
the service user, virtualenv, and environment file. Root's shell and the service
can use different proxy settings or clients. Avoid printing environment files,
tokens, or signed download URLs in diagnostic output.

In the reported Debian 13 CT, the resolver was `192.168.0.1` and the NSS hosts
order was `files dns`. The same service-user Python/HTTPX probe produced:

| Process resolver options | DNS result | Model configuration HEAD |
|---|---|---|
| Baseline (`timeout:2 attempts:1`) | IPv4 results after a 2-second delay | `ConnectError`, underlying `ConnectionRefusedError` / errno 111 |
| Add `single-request-reopen` | IPv4 and IPv6 results without the delay | HTTP 200 |
| Add `no-aaaa` | IPv4 results without the delay | HTTP 200 |

This identifies an A/AAAA lookup interaction along the DNS path.
`single-request-reopen` avoids reusing the socket between the A and AAAA
queries and retains both address families. These observations do not locate
the fault in a particular DNS server or firewall. A successful HEAD also does
not verify large-file transfers, Xet endpoints, or model integrity.

## Configure the demonstrated service workaround

For an affected CT, add this to its runtime host variables:

```yaml
ct_runtime_vllm_resolver_options: single-request-reopen
```

The role writes `RES_OPTIONS=single-request-reopen` to its managed environment
file, `/etc/default/vllm` by default. The value is inherited by the service's
glibc resolver. It does not change CT nameservers, global IPv6 settings, or the
controller's resolver. Other programs outside this service may still need a DNS
infrastructure fix. Leave the empty default on unaffected systems; remove the
override once the DNS path is fixed and service-user probes pass without it.

The runtime playbook enables and starts vLLM, and environment changes notify a
restart. During storage recovery, keep the model service stopped until physical
pool headroom has been verified. Budget missing repository files, partial
downloads, and runtime writes before resuming. An existing cache's apparent size
does not establish that every requested model file is complete or intact.
See [CT storage recovery](troubleshooting-ct-storage.md).
