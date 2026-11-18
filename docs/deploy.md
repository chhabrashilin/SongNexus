# Deploying SongNexus

Staging deploys automatically on every push to `v2` once the one-time setup below
is done (`.github/workflows/deploy.yml`). Until then the workflow is skipped.

```
GitHub (push to v2)
  └─ deploy.yml ── WIF ──▶ Artifact Registry (image: server:<sha>)
                       ├─▶ Cloud Run job  songnexus-migrate   (runs first, --wait)
                       ├─▶ Cloud Run svc  songnexus-api       (Cloud SQL via connector)
                       └─▶ Firebase Hosting (web/dist; /v1/** rewritten to the service)
```

## One-time setup (about an hour)

Replace `PROJECT` and `REGION` (we use `us-central1`, which the Hosting rewrite names).

1. **Project and APIs**
   ```sh
   gcloud config set project PROJECT
   gcloud services enable run.googleapis.com sqladmin.googleapis.com \
     artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com
   ```
2. **Image registry:** `gcloud artifacts repositories create songnexus --repository-format=docker --location=REGION`
3. **Database:** the smallest Cloud SQL for PostgreSQL 16 instance, private to the connector (no authorized networks).
   Create database `songnexus` and user `songnexus`. Store the URL as a secret:
   ```sh
   printf 'postgresql+psycopg://songnexus:PASSWORD@/songnexus?host=/cloudsql/PROJECT:REGION:INSTANCE' |
     gcloud secrets create songnexus-database-url --data-file=-
   ```
4. **Service accounts (least privilege)**
   | Account | Roles |
   |---|---|
   | `songnexus-api` | Cloud SQL Client; Secret Accessor on `songnexus-database-url` |
   | `songnexus-jobs` | Cloud SQL Client; Secret Accessor on `songnexus-database-url` |
   | `songnexus-deploy` (CI) | Run Admin; Artifact Registry Writer; Firebase Hosting Admin; Service Account User on the two above |
5. **Workload Identity Federation** for GitHub (no keys): create a pool and an OIDC provider for
   `https://token.actions.githubusercontent.com` with attribute condition
   `assertion.repository == "OWNER/REPO" && assertion.ref == "refs/heads/v2"`, and grant
   `roles/iam.workloadIdentityUser` on `songnexus-deploy` to that principal set.
6. **Firebase:** add Firebase to the project, enable Hosting and Authentication (Google provider), and set
   the auth domain to the Hosting domain so sign-in works without third-party cookies.
7. **GitHub:** create environment `staging` (with required reviewers for demo promotion) and repository
   variables `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `CLOUDSQL_INSTANCE`,
   `WEB_ORIGIN` (the Hosting origin, e.g. `https://PROJECT.web.app`). The service refuses to start outside
   development without allowed origins and a Firebase project, or with the Auth emulator configured.
8. **Budget:** a $25/month budget alert on the billing account (plan §18).
9. **Purge schedule:** `gcloud scheduler jobs create http songnexus-purge-daily --schedule "17 3 * * *"
   --uri "https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/songnexus-purge:run"
   --http-method POST --oauth-service-account-email songnexus-jobs@PROJECT.iam.gserviceaccount.com`.
10. **Keep search queries out of logs:** Cloud Run request logs record full URLs, including the `query=`
   of `/v1/catalog:search`. Exclude those entries (the service's own logs never contain queries):
   ```sh
   gcloud logging sinks update _Default --add-exclusion=name=search-queries,filter='resource.type="cloud_run_revision" AND httpRequest.requestUrl:"/v1/catalog:search"'
   ```
11. **First catalog build:** `gcloud run jobs execute songnexus-ingest --region REGION --wait`.
   It fails (non-zero exit) if the quality gate fails, and the service keeps serving the previous catalog.

## Releasing

- **Build once, promote:** the demo environment deploys the same image digest that passed staging.
- **Migrations** are expand/contract: never ship a breaking schema change with the code that needs it.
- **Rollback:** `gcloud run services update-traffic songnexus-api --to-revisions=PREVIOUS=100`, plus the
  feature-flag kill switch (`SONGNEXUS_FLAGS='{"play": false}'`) when one surface misbehaves.
- **New catalog:** commit the new snapshot, deploy, run `songnexus-ingest`. Instances pick up the new
  version within a minute (the read model polls) without a restart.

## Local equivalent

```sh
docker build -f server/Dockerfile -t songnexus-server .
docker run --rm -p 18080:8080 -e SONGNEXUS_DATABASE_URL=sqlite:////tmp/c.db songnexus-server \
  sh -c 'songnexus ingest && exec uvicorn songnexus.service.app:create_app --factory --host 0.0.0.0 --port 8080'
```
