# Auth misconfiguration

**Symptoms:** `POST /v1/sessions` returns 401/403 for everyone, or the new revision fails to start.

**Checks, in order:**
1. **Startup refusal.** Outside development the service exits unless `SONGNEXUS_ALLOWED_ORIGINS` (https only) and
   `SONGNEXUS_FIREBASE_PROJECT_ID` are set and the Auth emulator is unset. Read the first log line of the revision.
2. **Project ID mismatch.** ID-token verification checks audience and issuer against `SONGNEXUS_FIREBASE_PROJECT_ID`;
   it must equal the web app's Firebase project.
3. **Origin allow-list.** Sign-in and every write check `Origin`; the Hosting domain (and any preview channel in use) must
   be in `SONGNEXUS_ALLOWED_ORIGINS`.
4. **Cookie.** The session cookie must be named `__session` (Firebase Hosting strips other names) and the site must be
   served through Hosting rewrites so the cookie is first-party.
5. **Authorized domains** in Firebase Auth must include the Hosting domain; Google sign-in must be enabled.
6. **Proxy hops.** `SONGNEXUS_TRUSTED_PROXY_HOPS` must match the real number of proxies, or every user shares one rate-limit
   bucket (429s) or can spoof their address.

**Mitigate:** fix the setting and redeploy, or roll back ([bad deploy](bad-deploy.md)). Browsing needs no sign-in, so the
product stays usable while this is fixed.
