# TIB-AV-A

<!-- ![](images/iart-salvator.png) -->


## Overview

<!-- The project iART is devoted to the development of an e-Research-tool for digitized, image-oriented research processes in the humanities and cultural sciences. It not only aims to improve the efficiency of retrieval in image databases but also offers various tools for analyzing image data, thereby enhancing scientific work and facilitating new theory formation. The motivation for the project stems from the fundamental importance of the comparative approach in art history, which targets the similarity of pictures and comes along with a rehabilitation of similarity thinking in contemporary philosophy of science. iART is supposed to transfer the approach of art history theorists and practitioners of Comparative Analysis to the digital age, and to extend it by virtue of modern information technology.  -->


## Installation

<!-- At a later point there will be a docker container provided here. -->


## Development setup


### Requirements
* [docker](https://docs.docker.com/get-docker/)
* [docker-compose](https://docs.docker.com/compose/install/)


### Setup process
1. Clone the TIB-AV-A repository including submodules:
    ```sh
    git clone https://github.com/TIBHannover/tibava.git
    cd tibava
    ```

2. Download and extract models:
    ```sh
    mkdir data/cache
    mkdir data/analyser
    mkdir data/media
    mkdir data/tmp
    mkdir data/predictions
    mkdir data/backend_cache
    wget https://tib.eu/cloud/s/kAe3TXPfsBpwtwk/download/models.tar.gz
    tar -xf models.tar.gz --directory data/
    ```

3. Build and start the container:
    ```sh
    sudo docker-compose up --build
    ```

4. Apply database migrations and build frontend packages:
    ```sh
    sudo docker-compose exec backend python3 backend/src/backend/manage.py migrate auth
    sudo docker-compose exec backend python3 backend/src/backend/manage.py migrate
    sudo docker-compose exec frontend npm install
    sudo docker-compose exec frontend npm run build
    ```

5. Go to the frontend instance at `http://localhost/`.


### Code reloading
Hot reloading is enabled for `backend`. To display frontend changes, run:
```sh
sudo docker-compose exec frontend npm run build
```
Alternatively, use `serve` to enable a hot reloaded instance on `http://localhost:8080/`:
```sh
sudo docker-compose exec frontend npm run serve
```

### Geolocation LLM configuration
The `geolocation` backend plugin calls an external LLM to guess where a shot was filmed, and needs two settings:
* `GEOLOCATION_LLM_API_KEY` — API key for the external LLM.
* `GEOLOCATION_LLM_API_URL` — endpoint to send requests to.

Set them either in `backend/src/backend/.env` (picked up automatically) or under a `[geolocation]` section in `backend/src/backend/backend_config.toml`, the same way the analyser service's `[analyser]` section configures `grpc_host`/`grpc_port`:
```toml
[geolocation]
api_url = "https://example.com/geolocate"
api_key = "sk-..."
```
The request/response shape is still a placeholder pending the real provider being chosen, so point `GEOLOCATION_LLM_API_URL` at whatever mock or real endpoint is available for now. Without both settings, the plugin fails immediately with a clear error instead of running.

### Testing LLM/API-based plugins without a real endpoint
`backend/src/backend/backend/views/llm_test_echo.py` is a small dev-only endpoint, routed at `llm/test-echo/<plugin_name>/`, for smoke-testing a plugin's outbound API call without a real external service. It only responds when `DEBUG=true` (404s otherwise), so it's safe to leave in the codebase rather than delete after each use.

To use it, point the plugin's API-URL setting at it and make sure `backend` is an allowed host, e.g. in `backend/src/backend/.env`:
```
DEBUG=true
ALLOWED_HOSTS=localhost,backend
GEOLOCATION_LLM_API_URL=http://backend:8000/llm/test-echo/geolocation/
GEOLOCATION_LLM_API_KEY=test-key
```
`http://backend:8000` (not `localhost`) is required because these calls originate from the `celery` container, addressing `backend` by its docker-compose service name; without `ALLOWED_HOSTS` including `backend`, Django rejects the request with `DisallowedHost`.

Watch what it receives with:
```sh
docker-compose logs -f backend celery
```
Each request is logged with any secret-looking headers (`Authorization`, or a name containing `key`/`token`/`secret`) masked, and any string over ~300 chars (e.g. a base64-encoded image) summarized as a length + `sha256` digest + short prefix instead of dumped in full — the hash makes it possible to tell identical vs. distinct payloads apart (e.g. to catch accidentally duplicated frames) without a raw, unreadable log line.

It responds with a fixed JSON body from the `FIXTURES` dict in that file, keyed by `plugin_name` (a `"geolocation"` entry is included; unregistered plugin names get `[]`). To exercise a new plugin's response-parsing/DB-write code end-to-end rather than just its outbound request, add a fixture entry there shaped like what that plugin's client expects.

> **Geolocation demo note:** This repository is a modified demo based on
> [TIB AV-Analytics](https://github.com/TIBHannover/tibava). It adds a mock
> geolocation map and shot timeline for UI demonstration only; no
> geolocation model output is used. This modified work remains licensed under
> the GPL-3.0; see [LICENSE](LICENSE).

<!-- ## About the project

iART was funded by the [DFG](https://gepris.dfg.de/gepris/projekt/415796915) from 2019 to 2021. Our team consists of [Matthias Springstein](https://www.tib.eu/de/forschung-entwicklung/visual-analytics/mitarbeiterinnen-und-mitarbeiter/matthias-springstein/), [Stefanie Schneider](https://www.kunstgeschichte.uni-muenchen.de/personen/wiss_ma/schneider/index.html), [Javad Rahnama](https://www.hni.uni-paderborn.de/ism/mitarbeiter/155385986504753/), [Ralph Ewerth](https://www.tib.eu/de/forschung-entwicklung/visual-analytics/mitarbeiterinnen-und-mitarbeiter/ralph-ewerth/), [Hubertus Kohle](https://www.kunstgeschichte.uni-muenchen.de/personen/professoren_innen/kohle/index.html), and [Eyke Hüllermeier](https://www.hni.uni-paderborn.de/ism/mitarbeiter/112491383000284/).


## Contributing

Please report issues, feature requests, and questions to the [GitHub issue tracker](https://github.com/TIBHannover/iart/issues). We have a [Contributor Code of Conduct](https://github.com/TIBHannover/iart/blob/master/CODE_OF_CONDUCT.md). By participating in iART you agree to abide by its terms. -->
