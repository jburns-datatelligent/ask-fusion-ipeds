# Public Ask Fusion (IPEDS) web app. Build from ipeds_demo/ so the image gets the agent client
# and the verified questions too:
#
#   docker build -f app/Dockerfile -t ask-fusion-ipeds .
#   docker run -p 8080:8080 --env-file app/.secrets/app.env \
#     -e SNOWFLAKE_PRIVATE_KEY="$(cat app/.secrets/svc_rsa_key.p8)" ask-fusion-ipeds
#
# On a host, set SNOWFLAKE_PRIVATE_KEY from its secret store; never bake the key into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080
WORKDIR /srv/ipeds_demo/app

COPY app/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/agent_client.py /srv/ipeds_demo/backend/agent_client.py
COPY semantic/verified_queries.yaml /srv/ipeds_demo/semantic/verified_queries.yaml
COPY app/ /srv/ipeds_demo/app/

RUN useradd --create-home --uid 10001 app && mkdir -p .data && chown -R app /srv/ipeds_demo/app/.data
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/_stcore/health')"
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0"]
