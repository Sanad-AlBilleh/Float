// Where the two services are. This file is the local default (docker compose); the CD pipeline
// overwrites it on Azure with the Container Apps' HTTPS addresses. No secrets belong here.
window.FLOAT_CONFIG = {
  personalUrl: "http://localhost:8001",
  householdsUrl: "http://localhost:8002",
};
