# TODO (28.09.2026)
- [X] Prevent a file that has already been inserted into a vector store from being inserted a second time
- [ ] Allow deletion of files just from the vector store without also deleting it from the S3 storage. At the moment, the /delete route also deletes the S3 file
- [ ] Add async job queue for embeddings. At the moment, everything is done synchronously within the request thread
- [ ] Optimize tokenization, pre-install required dockling packages during container image creation. At the moment, dockling downloads required dependencies on the fly depending on the uploaded file format
- [ ] Add format filter for uploaded files
- [ ] Optimize document chunking, tokenization. At the moment, dockling tokenizes documents on the CPU in the request thread with a small model downloaded from huggingface
- [ ] Implement quota system for S3 storage, vector DB storage, amount of created vector stores
- [ ] Verify file ownership/team when attaching a file to a vector store
- [ ] Split project into more files to increase readability

# SETUP
- Copy `env.example` to `.env`, enter values
- Install uv, then run `uv sync` to create the project environment
- Create a docker contianer from the Dockerifle or run the Devcontainer in `.devcontainer/devcontainer.json`. 
  - When running the Devcontainer: You will need to adjust the `runArgs` parameter, depending on your setup. Currently, it is used to connect the created container to a docker network that contains the litellm service.
  - When running the Devcontainer: Run `uv run python main.py` within the devcontainer to start the application.
- On startup, the Vector extension in Postgres will be enabled and the database tables will be created.
- Look at the API routes at http://localhost:8000/docs when the container is running. API routes require a HTTP Bearer token that is a valid LiteLLM virtual key.
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
LITELLM_API_KEY="your-litellm-admin-key"

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
- `LITELLM_API_KEY` - LiteLLM admin key used to look up incoming virtual keys

## Integrate with an existing LiteLLM installation

This application runs as a separate internal API service alongside LiteLLM. When using LiteLLM's `pg_vector` vector-store provider, clients send vector-store requests to LiteLLM and LiteLLM calls this service. The app calls LiteLLM for key validation and embedding generation. No ingress is needed for `litellm-pgvector` when LiteLLM can reach its Kubernetes Service; keep the app service as `ClusterIP`. If clients call this app directly from outside the cluster, expose it separately.

Set the app's configuration to your existing LiteLLM proxy and embedding model alias:

```dotenv
EMBEDDING__BASE_URL=http://litellm.litellm.svc.cluster.local:4000
EMBEDDING__MODEL=litellm_proxy/<embedding-model-alias>
EMBEDDING__DIMENSIONS=3072
LITELLM_API_KEY=<litellm-admin-key>
```

The `LITELLM_API_KEY` value must be allowed to call LiteLLM's `/key/info` endpoint. Keep it secret. Configure LiteLLM's `pg_vector` provider to use the internal service URL `http://litellm-pgvector.litellm-pgvector.svc.cluster.local:8000` as its API base, along with a valid LiteLLM virtual key for the backend API key. The provider calls this service over cluster networking; clients continue to use LiteLLM's existing endpoint. The app scopes stores to the identity of the key LiteLLM sends to it, so use a team key when stores should be shared by that team. Configure the embedding alias in LiteLLM and ensure it returns 3072-dimensional vectors, matching the app's fixed PGVector column.

The app also needs PostgreSQL with the `vector` extension and an S3-compatible object store for uploaded files. The Kubernetes CNPG Cluster manifest creates the database and extension. For other installations, the database URL must include a schema query parameter, such as `?schema=public`, and the database user needs permission to create the schema and extension on first startup, or an administrator must create them beforehand.

For direct in-cluster API access, the service address is `http://litellm-pgvector.litellm-pgvector.svc.cluster.local:8000`. For LiteLLM's `pg_vector` provider, configure that service as the backend and keep client traffic on LiteLLM's existing endpoint.

## Kubernetes deployment

The `k8s/` directory contains the app Deployment and internal Service, ConfigMap, and a three-instance CNPG PostgreSQL Cluster for the `litellm-pgvector` namespace. The database uses persistent 20Gi volumes per instance and the CloudNativePG standard PostgreSQL 17 image, which includes pgvector. The manifest creates the `litellm_pgvector` database and installs the `vector` extension. CNPG generates the application password in its `litellm-pgvector-db-app` Secret; the Deployment reads it as `PGPASSWORD`. Update `k8s/configmap.yaml` with your LiteLLM Service name, embedding alias, and S3 endpoint details. The default embedding dimension is 3072. Install the CNPG operator in the cluster before applying these manifests.

Create a local file named `.k8s-secrets` with the app's other secrets (do not commit it):

```dotenv
LITELLM_API_KEY=your-litellm-admin-key
S3_ACCESS_KEY=your-s3-access-key
S3_SECRET_KEY=your-s3-secret-key
```

Create the Kubernetes Secret, then apply the resources:

```bash
kubectl create namespace litellm-pgvector --dry-run=client -o yaml | kubectl apply -f -
kubectl -n litellm-pgvector create secret generic litellm-pgvector-secrets \
  --from-env-file=.k8s-secrets
kubectl apply -k k8s/
```

The database password is generated by CNPG, so no database password needs to be committed or sealed. The manually created Secret contains only the LiteLLM and S3 credentials. The CI workflow builds the container on pull requests and publishes `main` images from the default branch. Release Please creates versioned releases and publishes versioned images to `ghcr.io/fhswf/litellm-pgvector`. Pin `k8s/deployment.yaml` to a release tag for production. If the GHCR package is private, configure an image pull Secret in the `litellm-pgvector` namespace and reference it from the Deployment.

The deployment starts with one replica and replaces the old pod before starting an updated pod because database schema setup runs during app startup. It uses an ephemeral model cache; use a PVC if you want to keep downloaded document models across pod replacements.

### Argo CD

Create the app's Kubernetes Secret first, then install the Argo CD Application manifest:

```bash
kubectl apply -n argocd -f argocd/application.yaml
```

The manifest tracks the `main` branch and deploys `k8s/` into the `litellm-pgvector` namespace. Create the namespace and app Secret first, then install the Argo CD Application. Change the repository URL, revision, and destination namespace in `argocd/application.yaml` if your GitOps setup uses different values.

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
