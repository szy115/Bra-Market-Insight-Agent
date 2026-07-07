const statusNode = document.querySelector("#status");

fetch("/api/health")
  .then((response) => {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  })
  .then((data) => {
    statusNode.textContent = `Backend health: ok at ${data.time || "now"}`;
  })
  .catch((error) => {
    statusNode.textContent = `Backend health check failed: ${error.message}`;
  });
