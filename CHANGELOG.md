# Changelog

## [1.5.0](https://github.com/fhswf/litellm-pgvector/compare/v1.4.0...v1.5.0) (2026-10-22)


### Features

* enhance file handling and metadata retrieval in ingestion and search processes ([992be23](https://github.com/fhswf/litellm-pgvector/commit/992be235e6e0657fc5d83d736b118107ed650450))
* improve chunking logic in compute_chunks method for better Markdown handling ([ba9f7e5](https://github.com/fhswf/litellm-pgvector/commit/ba9f7e5bacd06fb372af568096c9cd797761417a))


### Bug Fixes

* **ingestion:** Update dependencies in pyproject.toml and uv.lock ([f7255fc](https://github.com/fhswf/litellm-pgvector/commit/f7255fc75286d6fc8b02536610db06f64ec5308e))

## [1.4.0](https://github.com/fhswf/litellm-pgvector/compare/v1.3.0...v1.4.0) (2026-10-21)


### Features

* add script to summarize unittest output and update CI workflow to include test summary ([19c3c43](https://github.com/fhswf/litellm-pgvector/commit/19c3c430f3d6dc902a9c801b0843989eb4f9c5e1))


### Bug Fixes

* correct type conversion for rapidocr model directory path ([d068cc0](https://github.com/fhswf/litellm-pgvector/commit/d068cc0ced9500bc7168c519faa56984ec382668))

## [1.3.0](https://github.com/fhswf/litellm-pgvector/compare/v1.2.0...v1.3.0) (2026-10-21)


### Features

* add support for OpenAI vector store provider and update related configurations ([8bc4bcd](https://github.com/fhswf/litellm-pgvector/commit/8bc4bcd0a29172cf85626ccc4040ebce65382b8b))
* enhance database interaction with lock handling and async support ([09b6668](https://github.com/fhswf/litellm-pgvector/commit/09b666807b29b67ff997a52aaba408d3be9af1b9))
* enhance document processing with PDF options and error logging in ingestion ([47477e0](https://github.com/fhswf/litellm-pgvector/commit/47477e040d5081521896c2a5f09ea5649d7e774a))
* implement user and team ownership for vector stores and files, enabling scoped access ([400db1a](https://github.com/fhswf/litellm-pgvector/commit/400db1a2e6e7ba4627edf291a4d02393b4c49ed4))

## [1.2.0](https://github.com/fhswf/litellm-pgvector/compare/v1.1.0...v1.2.0) (2026-10-04)


### Features

* add CI PR report workflow and enhance integration test output reporting ([baf5634](https://github.com/fhswf/litellm-pgvector/commit/baf5634d557f7ed36275a25d82fb605323d6cb7c))
* add integration tests for file lifecycle with PostgreSQL and mock S3 ([fb70b55](https://github.com/fhswf/litellm-pgvector/commit/fb70b55ae6b3fdd1cd0ff17e2b1b0d0efdd0360a))
* enhance file ingestion and management with async processing and improved error handling ([5303076](https://github.com/fhswf/litellm-pgvector/commit/5303076afe01f4b5682d6f3c52d52e884201d797))


### Bug Fixes

* update S3 configuration to use dynamic region and bucket settings ([35b1e8e](https://github.com/fhswf/litellm-pgvector/commit/35b1e8ef06fae6ccae2064dff80900e5ddee3892))

## [1.1.0](https://github.com/fhswf/litellm-pgvector/compare/v1.0.0...v1.1.0) (2026-10-01)


### Features

* add psycopg2-binary dependency to project ([8900d81](https://github.com/fhswf/litellm-pgvector/commit/8900d81dcda3914bd02f3b0eca17f204146165fd))
* add sealed secrets management script and configuration for Kubernetes ([126dc93](https://github.com/fhswf/litellm-pgvector/commit/126dc93b36e20fb2f8c4a1610fe09e5f5042dfe3))
* enhance vector store management with private team support and API key validation ([243f125](https://github.com/fhswf/litellm-pgvector/commit/243f12569694926628a7d7cbdd139b9032d973cd))
* update embedding model and add vector store configuration in configmap.yaml ([c05dbb9](https://github.com/fhswf/litellm-pgvector/commit/c05dbb92e67e8a38bcf0df95a763373d34b2637e))
* update README and Kubernetes manifests for litellm-pgvector deployment ([b198ea5](https://github.com/fhswf/litellm-pgvector/commit/b198ea52cc7428662a325d56c2f17d3f9ff62718))
* update release configuration and deployment settings ([38672c2](https://github.com/fhswf/litellm-pgvector/commit/38672c2b52bd2408bc25efce79eb0d4cb99bcf26))


### Bug Fixes

* correct branch name extraction in release workflow ([6c1cb05](https://github.com/fhswf/litellm-pgvector/commit/6c1cb05e866e4459f25c63f0172d82078cad2c64))
* multiple assignments to same column "file_counts" ([460d78b](https://github.com/fhswf/litellm-pgvector/commit/460d78bb269c163b258a28a79f28a7427ecc09c7))
* update encrypted secrets in sealed-secret.yaml ([a098eb5](https://github.com/fhswf/litellm-pgvector/commit/a098eb57f5d9ada502784583d60b963dcf0437ab))
