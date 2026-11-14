# Financial Complaint Router

Banks receive thousands of customer complaints and usually sort them by hand, which is slow and inconsistent. This project is an AI web application that reads a complaint and, in under a second:

- **routes it** to the right product category and team (9 categories),
- **flags it as high priority** if it needs fast handling,
- shows a **confidence score** and the **words that drove the decision**,
- lists **similar past complaints** to help the agent.

The whole ML lifecycle is automated with AIOps tools: **DVC** pipeline, **Ray** data processing, **MLflow** tracking and serving, **FastAPI** backend, **Docker Compose**, and **Prometheus + Grafana** monitoring with automatic retraining when data drift is detected.

**Current model:** SGD linear classifier on TF-IDF features, trained on real CFPB complaints. Test accuracy **0.82**, macro-F1 **0.80**, urgent-complaint recall **0.74**.

---

## Contents

1. [How it works](#1-how-it-works)
2. [Project structure](#2-project-structure)
3. [Requirements](#3-requirements)
4. [Setup (one time)](#4-setup-one-time)
5. [Running the application](#5-running-the-application)
6. [Using the application](#6-using-the-application)
7. [The ML pipeline](#7-the-ml-pipeline)
8. [Experiments and reproducibility](#8-experiments-and-reproducibility)
9. [Monitoring and automatic retraining](#9-monitoring-and-automatic-retraining)
10. [Testing and CI](#10-testing-and-ci)
11. [Command reference](#11-command-reference)
12. [Troubleshooting](#12-troubleshooting)
13. [Documentation](#13-documentation)

---

## 1. How it works

```
                 REST                  REST
  Web UI  ───────────────►  Backend  ──────────►  Model server  ◄── loads @champion ──  MLflow
 (nginx)                   (FastAPI)            (mlflow serve)                      (tracking +
  :8080                      :8000                  :5001                            registry) :5000
                               │                                                         ▲
                               │ metrics                                                 │ logs runs,
                               ▼                                                         │ registers models
                          Prometheus ──► Grafana (dashboards)                            │
                            :9090          :3000                                         │
                               │ drift alert                                             │
                               ▼                                                         │
                         Alertmanager ──webhook──► Retrainer ──runs──► DVC pipeline ─────┘
                            :9093                    :8001       (ingest → … → register)
```

Each box is a separate Docker container. The main ideas:

- **The UI and the model are independent.** The UI only calls the backend's REST API. The backend calls the model server over REST too, so a new model can go live without touching the UI or API.
- **Training is a DVC pipeline.** `dvc repro` runs: unit tests → ingest → preprocess (Ray) → validate → split → train → evaluate → register.
- **MLflow decides what's live.** Each trained model is registered in MLflow. It becomes `@champion` only if it passes quality checks and beats the current champion. The model server always serves `@champion`.
- **Monitoring closes the loop.** If the incoming complaints start looking different from the training data (drift), Prometheus fires an alert and the retrainer runs the pipeline again automatically.

The full diagram and the job of each block are described in [docs/architecture.md](docs/architecture.md).

## 2. Project structure

```
src/complaint_router/       Shared Python package
  categories.py               9 categories, product mapping, priority keywords
  text_cleaning.py            text cleaning + PII masking (used in training and prediction)
  model/router_model.py       the model: TF-IDF + classifier + priority + explanation + similar complaints
  pipeline/                   one file per DVC stage (ingest, preprocess, validate, split, train, evaluate, register)
  monitoring/drift.py         drift statistics (PSI, out-of-vocabulary rate)
backend/app/                FastAPI backend (REST API, metrics, drift monitor, feedback)
frontend/                   Web UI (HTML/CSS/JS served by nginx)
services/model_server/      Keeps `mlflow models serve` on the @champion model
services/retrainer/         Runs the DVC pipeline when an alert or admin asks
monitoring/                 Prometheus, Alertmanager and Grafana configuration
docker/ml.Dockerfile        Image for MLflow, model server and retrainer
tests/                      unit, integration and end-to-end tests
scripts/                    setup, CI, smoke test, drift demo, rollback, report/PDF builders
docs/                       architecture, HLD, LLD, test plan/report, user manual

dvc.yaml                    the pipeline (stages, inputs, outputs)
params.yaml                 every setting of the pipeline
docker-compose.yml          all 10 services
MLproject                   MLflow project definition
Makefile                    short commands for everything (`make help`)
```

## 3. Requirements

- Ubuntu 22.04 or 24.04 (a VirtualBox VM works)
- **8 GB RAM or more for the VM** (6 GB minimum), 4 CPUs, 30 GB free disk
- Internet access for the first build and the first data download

Everything else (Docker, Git LFS, DVC, Python 3.11) is installed by the setup script. **No cloud services are used.**

> **VirtualBox tip:** give the VM about 60% of your computer's RAM and keep the slider in the green zone. Change it only while the VM is powered off. Avoid running heavy programs (e.g. a browser with many tabs) in the VM while training.

## 4. Setup (one time)

```bash
# 1. Get the code
git clone <your-repo-url> AIOps_project
cd AIOps_project

# 2. Install Docker, git-lfs, DVC and the Python venv; set up the local DVC
#    remote, git hooks and the .env file with secrets
bash scripts/setup_ubuntu.sh
newgrp docker            # only if Docker was just installed
```

`.env` holds the secrets (admin token, encryption key). It is private and never committed; `.env.example` shows what it contains.

## 5. Running the application

```bash
# Start all 10 services (first build takes ~10 minutes)
make up

# Train the first model (only needed once)
make train            # real CFPB data: downloads ~114 MB, takes ~5 minutes
# or
make train-sample     # small bundled sample: offline, ~1 minute

# Check that everything is healthy and make a test prediction
make smoke
```

Then open the web app at **http://localhost:8080**. The status light turns green within about 20 seconds of training finishing.

| Service | URL | What it's for |
|---|---|---|
| Web app | http://localhost:8080 | the application for agents |
| API docs (Swagger) | http://localhost:8000/docs | try the REST API |
| MLflow | http://localhost:5000 | experiments, metrics, model versions |
| Grafana | http://localhost:3000 | live dashboards (admin password is in `.env`) |
| Prometheus | http://localhost:9090 | raw metrics and alert status |
| Alertmanager | http://localhost:9093 | fired alerts |

Stop everything with `make down`. Your data, models and MLflow history are kept.

**Opening it from Windows (outside the VM):** in VirtualBox → *Settings → Network → Adapter 1 → Port Forwarding*, add rules for ports 8080, 8000, 3000, 5000, 9090 and 9093 (host port = guest port). Then use the same `localhost` URLs in Windows.

## 6. Using the application

1. Open http://localhost:8080. The **Route a complaint** tab opens first.
2. Paste a complaint (at least 20 characters) or click one of the examples, then press **Route complaint**.
3. You'll see the **team**, **category**, **confidence**, **priority flag**, the **key words** behind the decision, and **similar past complaints**.
4. Press **Correct** if the result is right, or pick the right team and press **Send correction**. Feedback is stored encrypted and used in the next training.

The other tabs are **Pipeline console** (pipeline graph, stage runs, failures, model versions, retrain button), **Monitoring** (live Grafana dashboards) and **Help**. The full guide for non-technical users is in [docs/user_manual.md](docs/user_manual.md).

## 7. The ML pipeline

The pipeline is defined in [dvc.yaml](dvc.yaml), and all its settings are in [params.yaml](params.yaml). `dvc repro` re-runs only the stages whose code, data or settings changed.

| Stage | What it does | Output |
|---|---|---|
| `ci_tests` | runs the unit tests; training stops if any fail | `reports/ci/unit_tests.xml` |
| `ingest` | downloads CFPB complaints (or uses the sample) | `data/raw/complaints.parquet` |
| `preprocess` | cleans text, masks personal data, maps categories, in parallel with **Ray** | `data/processed/complaints_clean.parquet` |
| `validate` | data-quality checks (columns, nulls, labels, row counts) | `reports/data_validation.json` |
| `split` | balances classes and splits train / validation / test | `data/splits/` |
| `train` | trains the model, logs everything to **MLflow** | `models/router.joblib` |
| `evaluate` | test metrics, confusion matrix, drift reference stats | `reports/metrics.json` |
| `register` | registers the model; promotes it to `@champion` only if it is good enough | `reports/registration.json` |

```bash
make dag        # show the pipeline graph
make metrics    # show the latest metrics
```

**Data:** CFPB Consumer Complaint Database (public domain, US government), read from the Apache-2.0 parquet mirror `davidheineman/consumer-finance-complaints-large` on HuggingFace, because the live CFPB export no longer includes complaint text. `data/sample/sample_complaints.csv` holds 2,250 real complaints (250 per category) for offline use.

## 8. Experiments and reproducibility

Every MLflow run is tagged with the **git commit** and the **MD5 of the training data**. To reproduce a run:

```bash
git checkout <git_commit tag from the MLflow run>
dvc checkout            # restores the exact data and model of that commit
make train
```

To try other settings (each experiment is logged in MLflow and DVC):

```bash
make compare            # trains logreg, cnb and sgd on the same data and prints a comparison
docker compose run --rm retrainer dvc exp run -S train.C=2.0      # one custom experiment
```

Data and models are versioned with DVC in a local folder (`~/dvc-storage`). After a good training run:

```bash
.venv/bin/dvc push
git add dvc.lock params.yaml reports/ && git commit -m "model: <what changed>"
```

To go back to an earlier model version (no rebuild needed):

```bash
make rollback VERSION=1
```

## 9. Monitoring and automatic retraining

- The backend exports metrics at `/metrics`: request rate, latency, errors, predicted categories, confidence, priority rate and drift scores.
- Prometheus collects them every 10 seconds, and Grafana shows them live.
- Alert rules ([monitoring/prometheus/alert_rules.yml](monitoring/prometheus/alert_rules.yml)) cover drift, high latency, errors, model down, failed retraining and high memory.
- **Drift → retraining:** when `DataDriftDetected` fires, Alertmanager calls the retrainer, which runs `dvc repro`. The new model goes live automatically if it passes the quality gate.

Try it yourself:

```bash
make drift      # sends unusual complaints → drift alert → automatic retraining
```

## 10. Testing and CI

```bash
make venv       # one time: create the local Python environment
make lint       # code style (ruff, PEP 8)
make test       # unit + integration tests (64 tests)
make report     # write docs/test_report.md from the latest test run
make test-e2e   # end-to-end tests against the running stack
make ci         # full local CI: lint, tests, report, DVC status, Docker build
```

A **git pre-push hook** runs the quick CI (lint, unit tests, DVC status) before every push. Cloud CI is not allowed in this project, so CI runs locally and inside the DVC pipeline (`ci_tests` stage).

## 11. Command reference

| Command | What it does |
|---|---|
| `make up` / `make down` | start / stop all services |
| `make ps` / `make logs` | service status / follow logs |
| `make train` | run the full pipeline on real data |
| `make train-sample` | run the pipeline on the bundled sample |
| `make compare` | train and compare the 3 model types |
| `make smoke` | health check + one test prediction |
| `make drift` | drift and retraining demo |
| `make rollback VERSION=n` | serve an older model version |
| `make test` / `make ci` | tests / full local CI |
| `make docs-pdf` | build `docs/Project_Documentation.pdf` |
| `make help` | list all commands |

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied ... docker.sock` | run `newgrp docker`, or log out and back in |
| `ADMIN_TOKEN ... run "make env" first` | run `make env` |
| UI says *Model offline* | no model trained yet: run `make train`, then check `docker compose logs model-server` |
| VM freezes or VS Code closes during training | not enough RAM: give the VM more memory, close other programs, or set `preprocess.num_cpus: 1` in `params.yaml` |
| `no space left on device` | `docker system prune` removes old containers and images |
| A service keeps restarting after a VM crash | its image may be corrupted: `docker compose build --no-cache <service>` then `make up` |
| Dataset download fails | set `ingest.source: sample` in `params.yaml` |
| Retrainer can't write files | `HOST_UID` / `HOST_GID` in `.env` must match `id -u` / `id -g` |

## 13. Documentation

All required documents are in [docs/](docs/), and also combined into one PDF: **[docs/Project_Documentation.pdf](docs/Project_Documentation.pdf)** (rebuild with `make docs-pdf`).

| Document | File |
|---|---|
| Architecture diagram and blocks | [docs/architecture.md](docs/architecture.md) |
| High-level design (design choices and reasons) | [docs/HLD.md](docs/HLD.md) |
| Low-level design (API endpoints, inputs and outputs) | [docs/LLD.md](docs/LLD.md) |
| Test plan and test cases | [docs/test_plan.md](docs/test_plan.md) |
| Test report (latest results) | [docs/test_report.md](docs/test_report.md) |
| User manual (for non-technical users) | [docs/user_manual.md](docs/user_manual.md) |
