# Changelog

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
