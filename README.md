# TODO (28.09.2026)
- [X] Prevent a file that has already been inserted into a vector store from being inserted a second time
- [X] Allow deletion of files just from the vector store without also deleting it from S3 storage
- [X] Queue file ingestion and embedding work outside the request
- [ ] Optimize tokenization, pre-install required dockling packages during container image creation. At the moment, dockling downloads required dependencies on the fly depending on the uploaded file format
- [ ] Add format filter for uploaded files
- [ ] Optimize document chunking and tokenization; the ingestion worker currently downloads its tokenizer from Hugging Face on first use
- [ ] Implement quota system for S3 storage, vector DB storage, amount of created vector stores
- [X] Verify file ownership when attaching a file to a vector store
- [ ] Split project into more files to increase readability

# SETUP
- Copy `env.example` to `.env`, enter values
- Install uv, then run `uv sync` to create the project environment
- Create a docker contianer from the Dockerifle or run the Devcontainer in `.devcontainer/devcontainer.json`. 
  - When running the Devcontainer: You will need to adjust the `runArgs` parameter, depending on your setup. Currently, it is used to connect the created container to a docker network that contains the litellm service.
  - When running the Devcontainer: Run `uv run python main.py` within the devcontainer to start the application.
- On startup, the Vector extension in Postgres will be enabled and the database tables will be created.
- Look at the API routes at http://localhost:8000/docs when the container is running. API routes require a HTTP Bearer token that is a valid LiteLLM virtual key.

## Local integration tests

The integration suite exercises the HTTP file routes, PostgreSQL counters and schema migration, and the background ingestion worker. S3 and LiteLLM embedding calls are stubbed, so no service credentials are needed. Each run creates a temporary PostgreSQL schema and removes it afterward.

```bash
docker run --rm -d --network host --name litellm-pgvector-test-db \
  -e PGPORT=55433 -e POSTGRES_PASSWORD=test -e POSTGRES_DB=testdb \
  pgvector/pgvector:pg17

TEST_DATABASE_URL='postgresql://postgres:test@127.0.0.1:55433/testdb' \
  uv run python -m unittest discover -s tests -v

docker stop litellm-pgvector-test-db
```

You can use an existing local PostgreSQL/pgvector database instead. Set `TEST_DATABASE_URL` to its connection URL; the test runner accepts only a loopback host and creates a fresh schema within that database.
-----

# OpenAI Vector Stores API with PGVector

A FastAPI application that provides OpenAI-compatible vector store endpoints using PGVector and LiteLLM proxy for embeddings.

## Features

- 🔌 OpenAI-compatible API endpoints
- 🗄️ PGVector for efficient vector storage and similarity search
- 🎛️ Configurable PostgreSQL schema
- 🔄 LiteLLM proxy integration for any embedding model
- 🐳 Docker support
- ⚡ FastAPI with async support

## API Endpoints

### Upload and ingest a file

The upload stores the original file and returns its ID. Attach that ID to a vector store to start parsing and embedding. Attachment returns `status: "in_progress"` immediately; poll the attachment until it reaches `completed` or `failed`.

```bash
curl -sS --fail-with-body https://pgvector.fh-swf.cloud/v1/files \
  -H "Authorization: Bearer $LITELLM_USER_KEY" \
  -F 'purpose=assistants' \
  -F 'file=@README.md;type=text/markdown'

curl -sS --fail-with-body -X POST \
  "https://pgvector.fh-swf.cloud/v1/vector_stores/$VECTOR_STORE_ID/files" \
  -H "Authorization: Bearer $LITELLM_USER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"file_id\":\"$FILE_ID\"}"

curl -sS --fail-with-body \
  "https://pgvector.fh-swf.cloud/v1/vector_stores/$VECTOR_STORE_ID/files/$FILE_ID" \
  -H "Authorization: Bearer $LITELLM_USER_KEY"
```

The file ID in the attachment response is the original uploaded file ID. `GET /v1/vector_stores/{id}/files` lists attachments, and `DELETE /v1/vector_stores/{id}/files/{file_id}` removes an attachment while keeping the uploaded file. `DELETE /v1/files/{file_id}` deletes the original file and all its attachments. Pending jobs are stored in PostgreSQL and resumed after an application restart. The worker uses `LITELLM_API_KEY` to call the embedding model, so configure that key with access to the embedding alias.

### 1. Create Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Support FAQ"
  }'
```

### 2. List Vector Stores
```bash
# List all vector stores
curl -X GET \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key"

# List with pagination (limit and after parameters)
curl -X GET \
  "http://localhost:8000/v1/vector_stores?limit=10&after=vs_abc123" \
  -H "Authorization: Bearer your-api-key"
```

### 3. Add Single Embedding to Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/embeddings \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Our return policy allows returns within 30 days of purchase.",
    "embedding": [0.1, 0.2, 0.3, ...],
    "metadata": {
      "category": "returns",
      "source": "faq",
      "id": "return_policy_1"
    }
  }'
```

### 4. Add Multiple Embeddings (Batch)
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/embeddings/batch \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddings": [
      {
        "content": "Our return policy allows returns within 30 days of purchase.",
        "embedding": [0.1, 0.2, 0.3, ...],
        "metadata": {"category": "returns"}
      },
      {
        "content": "Shipping is free for orders over $50.",
        "embedding": [0.4, 0.5, 0.6, ...],
        "metadata": {"category": "shipping"}
      }
    ]
  }'
```

### 5. Search Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/search \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the return policy?",
    "limit": 20,
    "filters": {"category": "support"}
  }'
```

## Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```bash
# Database Configuration
DATABASE_URL="postgresql://username:password@localhost:5432/vectordb?schema=public"

# Server Configuration
HOST="0.0.0.0"
PORT=8000

# LiteLLM Proxy Configuration
EMBEDDING__MODEL="litellm_proxy/my-embedding-model"
EMBEDDING__BASE_URL="http://localhost:4000"
EMBEDDING__DIMENSIONS=3072
VECTOR_STORE_API_BASE="http://localhost:8000"
VECTOR_STORE_PROVIDER="openai"
LITELLM_API_KEY="your-litellm-admin-key"
LITELLM_VECTOR_STORE_REGISTRY_API_KEY="private-team-management-key"
LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID="private-registry-team-id"

# S3-compatible object storage
S3_HOST=""
S3_REGION=""
S3_ACCESS_KEY=""
S3_SECRET_KEY=""
S3_BUCKET=""
```

### Database Field Mapping

Database table and column names are currently fixed by the application.

### LiteLLM Proxy Configuration

The application sends embedding requests to the LiteLLM proxy and uses its key-info endpoint to validate incoming virtual keys. Configure it with:

- `EMBEDDING__MODEL` - LiteLLM model alias for an embedding deployment
- `EMBEDDING__BASE_URL` - LiteLLM proxy URL (e.g., "http://localhost:4000")
- `EMBEDDING__DIMENSIONS` - Embedding dimensions (the current PGVector column is fixed at 3072)
- `LITELLM_API_KEY` - LiteLLM admin credential used to validate keys, update key permissions, and delete registrations
- `VECTOR_STORE_API_BASE` - URL LiteLLM uses to call this app (use the Kubernetes Service URL in-cluster)
- `VECTOR_STORE_PROVIDER` - LiteLLM provider used for new store registrations: `openai` or `pg_vector` (default). Use `openai` for vector-store file listing through LiteLLM. The app adds `/v1` to its registered API base for this provider.
- `LITELLM_VECTOR_STORE_REGISTRY_API_KEY` - Separate, non-admin LiteLLM key assigned to a private, app-only team; used for fallback user-store registration
- `LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID` - The ID of that private team, used to verify the registry key's team membership
- `LITELLM_USER_SCOPED_VECTOR_STORES` - Enable user-owned registrations only after patching LiteLLM's user-level access check

## Integrate with an existing LiteLLM installation

This application runs as a separate internal API service alongside LiteLLM. Clients send vector-store requests to LiteLLM, which calls this service using the configured provider. The app calls LiteLLM for key validation and embedding generation. No ingress is needed for `litellm-pgvector` when LiteLLM can reach its Kubernetes Service; keep the app service as `ClusterIP`. If clients call this app directly from outside the cluster, expose it separately.

Set the app's configuration to your existing LiteLLM proxy and embedding model alias. In Kubernetes, LiteLLM's `api_base` for the connector should be the internal service URL, so the LiteLLM server can reach it without exposing the service publicly.

```dotenv
EMBEDDING__BASE_URL=http://litellm.litellm.svc.cluster.local:4000
EMBEDDING__MODEL=litellm_proxy/<embedding-model-alias>
EMBEDDING__DIMENSIONS=3072
LITELLM_API_KEY=<litellm-admin-key>
LITELLM_VECTOR_STORE_REGISTRY_API_KEY=<private-team-management-key>
LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID=<private-registry-team-id>
LITELLM_USER_SCOPED_VECTOR_STORES=false
VECTOR_STORE_API_BASE=http://litellm-pgvector.litellm-pgvector.svc.cluster.local:8000
VECTOR_STORE_PROVIDER=openai
```

These LiteLLM settings have different roles:

| Setting | Value to provide | How the app uses it |
| --- | --- | --- |
| `LITELLM_API_KEY` | A LiteLLM proxy admin credential authorized to call `/key/info`, `/key/update`, and `/vector_store/delete` | Validates keys, grants the creating key access in the fallback mode, and removes registrations. This is an internal admin credential, not a key users should send when creating a store. |
| `LITELLM_VECTOR_STORE_REGISTRY_API_KEY` | A **different, non-admin** LiteLLM management key belonging to a dedicated private team | Registers user stores in the fallback mode. LiteLLM associates those registrations with the private team. |
| `LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID` | The LiteLLM `team_id` of that dedicated team, **not** a key or user ID | Compares it with the registry key's `team_id` returned by `/key/info` before registering a store. Registration fails if they differ or if the creating key belongs to the registry team. This ID is not a secret. |
| `LITELLM_USER_SCOPED_VECTOR_STORES` | `false` until the LiteLLM user access patch is deployed | When `true`, registers a key without `team_id` under that key's `user_id`, so every key with that `user_id` can access the store. |

Use two distinct keys: the admin key needs permission to inspect and update user keys and delete registrations, while the registry key needs `/vector_store/new` for the user-store fallback. Create a private LiteLLM team for the registry key and put no end-user keys in it. Keep both API keys secret; in the Kubernetes deployment, the keys belong in the Secret and the team ID belongs in the ConfigMap.

Call this app's `POST /v1/vector_stores` with the intended owner's LiteLLM key. A key with `team_id` creates a team store: the app records that team, registers the store in LiteLLM with the same key, and allows every member key of that team to use the local store and files. That creating key must be allowed to call LiteLLM's `/vector_store/new` management route. If the key also has a `user_id`, its user's personal stores remain accessible with that key. A key without `team_id` creates a personal store and must have `user_id`; local access works from any key with the same `user_id`.

The rolled out LiteLLM 1.104.0 records a registration's `team_id` and `user_id` from the key used on `/vector_store/new`, but its access checks ignore `user_id` and treat a store with no `team_id` as public when accessed by ID. **Apply [the LiteLLM 1.104.0 user access patch](patches/litellm-1.104.0-user-vector-store-access.patch) to the LiteLLM proxy before setting `LITELLM_USER_SCOPED_VECTOR_STORES=true`.** The patch updates both the access and list checks so user-owned stores are available to keys with the same `user_id`, while team stores remain restricted to their team. A user key also needs permission to call LiteLLM's `/vector_store/new` management route in this mode. The patch must be adapted if the deployed LiteLLM version differs from 1.104.0.

Until the proxy is patched and the setting is enabled, personal stores keep the previous private-team registration with an explicit grant to the creating key. That prevents public LiteLLM access, but other keys with the same `user_id` cannot use the store through LiteLLM. Previously registered stores retain their existing LiteLLM owner and access rules; changing the setting affects new registrations only.

The store appears in LiteLLM's Vector Stores UI; users do not need to manually choose or copy a UUID there. LiteLLM forwards the creating key to this app for store requests, so keep that key active while the registration is in use. Configure the embedding alias in LiteLLM and ensure it returns 3072-dimensional vectors, matching the app's fixed PGVector column.

New stores use the creator key's scope. Existing LiteLLM registrations keep their current owner and access settings; review and re-register them if they need the new scope.

Changing `VECTOR_STORE_PROVIDER` affects new registrations only. Existing LiteLLM registrations must be re-registered to use the new provider and API base.

For a local test against the Kubernetes `ClusterIP` service, forward its port and create a store with the user's LiteLLM key:

```bash
kubectl port-forward -n litellm-pgvector svc/litellm-pgvector 8000:8000
```

In another terminal:

```bash
curl -X POST http://127.0.0.1:8000/v1/vector_stores \
  -H "Authorization: Bearer $LITELLM_USER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Support FAQ"}'
```

The response contains the generated vector store ID. The app registers that ID automatically, and it then appears in LiteLLM's Vector Stores UI. For end-user access outside the cluster, expose this app through an authenticated HTTPS ingress or gateway. LiteLLM itself should keep using the in-cluster `VECTOR_STORE_API_BASE` URL.

The app also needs PostgreSQL with the `vector` extension and an S3-compatible object store for uploaded files. The Kubernetes CNPG Cluster manifest creates the database and extension. For other installations, the database URL must include a schema query parameter, such as `?schema=public`, and the database user needs permission to create the schema and extension on first startup, or an administrator must create them beforehand.

For direct in-cluster API access, the service address is `http://litellm-pgvector.litellm-pgvector.svc.cluster.local:8000`. Set that service address as `VECTOR_STORE_API_BASE` and keep client traffic on LiteLLM's existing endpoint.

## Kubernetes deployment

The `k8s/` directory contains the app Deployment and internal Service, ConfigMap, and a three-instance CNPG PostgreSQL Cluster for the `litellm-pgvector` namespace. The database uses persistent 20Gi volumes per instance and the CloudNativePG standard PostgreSQL 17 image, which includes pgvector. The manifest creates the `litellm_pgvector` database and installs the `vector` extension. CNPG generates the application password in its `litellm-pgvector-db-app` Secret; the Deployment reads it as `PGPASSWORD`. Update `k8s/configmap.yaml` with your LiteLLM Service name, embedding alias, and S3 endpoint details. The default embedding dimension is 3072. Install the CNPG operator in the cluster before applying these manifests.

Edit the ignored local `.k8s-secrets` file with the app's real credentials. The local file currently contains placeholders; the script refuses to seal them until you replace them. `LITELLM_VECTOR_STORE_REGISTRY_API_KEY` must be a management key from the private registry team described above. After adding it and setting `LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID` in the ConfigMap, run the sealing script again and deploy the regenerated `k8s/sealed-secret.yaml`.

```dotenv
LITELLM_API_KEY=your-real-litellm-admin-key
LITELLM_VECTOR_STORE_REGISTRY_API_KEY=your-private-team-management-key
S3_ACCESS_KEY=your-real-s3-access-key
S3_SECRET_KEY=your-real-s3-secret-key
```

Install the Sealed Secrets controller in the cluster and install `kubeseal` locally. Generate an encrypted manifest with:

```bash
./k8s/create-sealed-secret.sh
```

The script seals a Secret named `litellm-pgvector-secrets` for the `litellm-pgvector` namespace, using strict name-and-namespace scope, and writes `k8s/sealed-secret.yaml`. By default, `kubeseal` fetches the public certificate from the current cluster; set `SEALED_SECRETS_CERT` to use a previously fetched certificate instead. Review and commit the generated encrypted manifest, never `.k8s-secrets`. Apply the SealedSecret before the app Deployment, or add `sealed-secret.yaml` to `k8s/kustomization.yaml` so Kustomize and Argo CD manage it:

```bash
kubectl apply -f k8s/sealed-secret.yaml
kubectl apply -k k8s/
```

The database password is generated by CNPG, so no database password needs to be committed or sealed. The SealedSecret contains only the LiteLLM and S3 credentials. CI runs the file lifecycle integration tests with PostgreSQL/pgvector before building the container on pull requests or publishing `main` images. Release Please creates versioned releases and publishes versioned images to `ghcr.io/fhswf/litellm-pgvector`. Its release pull request updates the image tag in `k8s/kustomization.yaml` to match the release. If the GHCR package is private, configure an image pull Secret in the `litellm-pgvector` namespace and reference it from the Deployment.

The deployment starts with one replica and replaces the old pod before starting an updated pod because database schema setup runs during app startup. It uses an ephemeral model cache; use a PVC if you want to keep downloaded document models across pod replacements.

### Argo CD

Generate and commit `k8s/sealed-secret.yaml`, and add it to `k8s/kustomization.yaml` before installing the Argo CD Application manifest. The Sealed Secrets controller must be running in the destination cluster:

```bash
kubectl apply -n argocd -f argocd/application.yaml
```

The manifest tracks the `main` branch and deploys `k8s/` into the `litellm-pgvector` namespace. Argo CD creates the namespace; make sure `sealed-secret.yaml` is listed in `k8s/kustomization.yaml` and committed before syncing the Application. Change the repository URL, revision, and destination namespace in `argocd/application.yaml` if your GitOps setup uses different values.

## Setup and Installation

### 1. Install Dependencies

```bash
uv sync
```

### 2. Database Setup

The Kubernetes deployment creates PostgreSQL with the `vector` extension using the CNPG Cluster resource. For a non-Kubernetes setup, create a PostgreSQL database with the extension available. The app creates its configured schema and tables on startup; see [the database requirements](#integrate-with-an-existing-litellm-installation).

### 3. Set up LiteLLM Proxy

Start LiteLLM proxy pointing to your preferred embedding model:

```bash
# Example: Start LiteLLM proxy for OpenAI
litellm --model text-embedding-ada-002 --port 4000
```

### 4. Run the Application

```bash
uv run python main.py
```

Or using uvicorn directly:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker Deployment

### Build and run with Docker:

```bash
# Build the image
docker build -t vector-store-api .

# Run the container
docker run -p 8000:8000 --env-file .env vector-store-api
```

## Database Schema

The application uses two main tables:

### vector_stores
- `id` (string, primary key)
- `name` (string)
- `file_counts` (json)
- `status` (string)
- `usage_bytes` (integer)
- `created_at` (timestamp)
- `expires_after` (json, optional)
- `expires_at` (timestamp, optional)
- `last_active_at` (timestamp, optional)
- `metadata` (json, optional)

### embeddings
- `id` (string, primary key)
- `vector_store_id` (string, foreign key)
- `content` (string)
- `embedding` (vector(1536))
- `metadata` (json, optional)
- `created_at` (timestamp)

## Supported Models

Any embedding model supported by LiteLLM proxy can be used. Examples:

- OpenAI: `text-embedding-ada-002`, `text-embedding-3-small`, `text-embedding-3-large`
- Cohere: `embed-english-v3.0`, `embed-multilingual-v3.0`
- Voyage: `voyage-2`, `voyage-large-2`
- And many more...

## API Response Format

### Vector Store Response
```json
{
  "id": "vs_abc123",
  "object": "vector_store",
  "created_at": 1699024800,
  "name": "Support FAQ",
  "usage_bytes": 0,
  "file_counts": {
    "in_progress": 0,
    "completed": 0,
    "failed": 0,
    "cancelled": 0,
    "total": 0
  },
  "status": "completed",
  "metadata": {}
}
```

### Vector Store List Response
```json
{
  "object": "list",
  "data": [
    {
      "id": "vs_abc123",
      "object": "vector_store",
      "created_at": 1699024800,
      "name": "Support FAQ",
      "usage_bytes": 1024,
      "file_counts": {"completed": 5, "total": 5},
      "status": "completed",
      "metadata": {}
    }
  ],
  "first_id": "vs_abc123",
  "last_id": "vs_def456",
  "has_more": false
}
```

### Search Response
```json
{
  "object": "vector_store.search",
  "data": [
    {
      "id": "emb_123",
      "content": "Return policy text...",
      "score": 0.95,
      "metadata": {"category": "support"}
    }
  ],
  "usage": {
    "total_tokens": 1
  }
}
```

## Example Search Request

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_support_faq/search \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I return an item?",
    "limit": 5,
    "return_metadata": true
  }'
```

## Health Check

```bash
curl http://localhost:8000/health
```

## Migrating Existing Data

If you have an existing database with embeddings and content, you can easily migrate using the embedding APIs:

### 1. Create Vector Store
First, create a vector store for your data:

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Migrated Data",
    "metadata": {"source": "legacy_system"}
  }'
```

### 2. Batch Insert Embeddings
Use the batch endpoint to efficiently insert multiple embeddings:

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_your_id/embeddings/batch \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddings": [
      {
        "content": "Your text content here",
        "embedding": [0.1, 0.2, 0.3, ...1536 dimensions...],
        "metadata": {"source_id": "doc_123", "category": "support"}
      }
    ]
  }'
```

### 3. Migration Script Example

Here's a Python script example for migrating from an existing database:

```python
import psycopg2
import requests
import json

# Connect to your existing database
conn = psycopg2.connect("your_existing_db_url")
cur = conn.cursor()

# Fetch existing data
cur.execute("SELECT content, embedding, metadata FROM your_table")
rows = cur.fetchall()

# Prepare batch data
embeddings = []
for content, embedding, metadata in rows:
    embeddings.append({
        "content": content,
        "embedding": embedding.tolist(),  # Convert numpy array to list
        "metadata": metadata or {}
    })

# Send batch to API
response = requests.post(
    "http://localhost:8000/v1/vector_stores/your_vector_store_id/embeddings/batch",
    headers={
        "Authorization": "Bearer your-api-key",
        "Content-Type": "application/json"
    },
    json={"embeddings": embeddings}
)

print(f"Migrated {len(embeddings)} embeddings")
```

## License

MIT License
