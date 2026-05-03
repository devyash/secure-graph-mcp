(() => {
  const svg = document.getElementById("graphSvg");
  const inspectorBody = document.getElementById("inspectorBody");
  const statusEl = document.getElementById("status");
  const loadBtn = document.getElementById("loadBtn");
  const agentIdEl = document.getElementById("agentId");
  const rootKeyEl = document.getElementById("rootKey");
  const depthEl = document.getElementById("depth");
  const ignoreEdgeAclEl = document.getElementById("ignoreEdgeAcl");
  const hideRedactedEdgesEl = document.getElementById("hideRedactedEdges");

  const state = {
    nodes: [],
    edges: [],
    rootId: null,
    selectedNodeId: null,
    draggedNodeId: null,
    dragOffset: { x: 0, y: 0 },
    simHandle: null,
  };

  function setStatus(text) {
    statusEl.textContent = text || "";
  }

  function qs() {
    return new URLSearchParams(window.location.search);
  }

  function applyQueryDefaults() {
    const q = qs();
    const agent = q.get("agent_id") || "";
    const root = q.get("root") || "";
    const depth = q.get("depth");

    agentIdEl.value = agent || "support_agent";
    rootKeyEl.value = root || "";
    if (depth) depthEl.value = depth;
    ignoreEdgeAclEl.checked = q.get("ignore_edge_acl") === "1";
    hideRedactedEdgesEl.checked = q.get("hide_redacted_edges") === "1";

    syncUrlFromInputs({ replace: true });
  }

  function syncUrlFromInputs({ replace }) {
    const params = new URLSearchParams();
    params.set("agent_id", agentIdEl.value.trim());
    params.set("root", rootKeyEl.value.trim());
    params.set("depth", String(Number(depthEl.value || 2)));
    if (ignoreEdgeAclEl.checked) params.set("ignore_edge_acl", "1");
    if (hideRedactedEdgesEl.checked) params.set("hide_redacted_edges", "1");

    const url = `${window.location.pathname}?${params.toString()}`;
    if (replace) window.history.replaceState({}, "", url);
    else window.history.pushState({}, "", url);
  }

  function parseNodeLabel(label) {
    const parts = String(label || "").split("\n");
    return { title: parts[0] || "", subtitle: parts[1] || "" };
  }

  function clearSvg() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
  }

  function ensureDefs() {
    let defs = svg.querySelector("defs");
    if (!defs) {
      defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      svg.appendChild(defs);
    }

    if (!defs.querySelector("#arrowheadNormal")) {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", "arrowheadNormal");
      marker.setAttribute("viewBox", "0 0 10 10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto-start-reverse");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      path.setAttribute("fill", "rgba(231,237,245,0.45)");
      marker.appendChild(path);
      defs.appendChild(marker);
    }

    if (!defs.querySelector("#arrowheadRedacted")) {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", "arrowheadRedacted");
      marker.setAttribute("viewBox", "0 0 10 10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto-start-reverse");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      path.setAttribute("fill", "rgba(255,176,74,0.75)");
      marker.appendChild(path);
      defs.appendChild(marker);
    }
  }

  function fitView(nodes) {
    if (!nodes.length) return;

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const n of nodes) {
      minX = Math.min(minX, n.x - n.r);
      minY = Math.min(minY, n.y - n.r);
      maxX = Math.max(maxX, n.x + n.r);
      maxY = Math.max(maxY, n.y + n.r);
    }

    const pad = 60;
    const vbW = Math.max(10, maxX - minX + pad * 2);
    const vbH = Math.max(10, maxY - minY + pad * 2);
    const originX = minX - pad;
    const originY = minY - pad;

    svg.setAttribute("viewBox", `${originX} ${originY} ${vbW} ${vbH}`);
  }

  function renderGraph(payload) {
    clearSvg();
    ensureDefs();

    const rootNumericId = payload.root ? payload.root.id : null;
    state.rootId = rootNumericId;

    const nodes = (payload.nodes || []).map((n) => {
      const { title, subtitle } = parseNodeLabel(n.label);
      const r = 26;
      return {
        raw: n,
        id: n.id,
        title,
        subtitle,
        x: Math.random() * 900 + 80,
        y: Math.random() * 600 + 80,
        vx: 0,
        vy: 0,
        r,
      };
    });

    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const edges = (payload.edges || []).map((e) => ({
      raw: e,
      source: nodeById.get(e.source_node_id),
      target: nodeById.get(e.target_node_id),
    })).filter((e) => e.source && e.target);

    state.nodes = nodes;
    state.edges = edges;

    const edgeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const nodeLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");

    // Build edge elements lazily during tick; keep placeholders
    edgeLayer.setAttribute("class", "edgeLayer");
    nodeLayer.setAttribute("class", "nodeLayer");

    for (const e of edges) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("class", e.raw.redacted ? "edge-path redacted" : "edge-path");
      path.setAttribute("marker-end", e.raw.redacted ? "url(#arrowheadRedacted)" : "url(#arrowheadNormal)");
      edgeLayer.appendChild(path);
      e.el = path;

      const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bg.setAttribute("class", "edge-label-bg");
      bg.setAttribute("rx", "6");
      bg.setAttribute("ry", "6");
      edgeLayer.appendChild(bg);
      e.bg = bg;

      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("class", "edge-label");
      text.setAttribute("text-anchor", "middle");
      edgeLayer.appendChild(text);
      e.text = text;

      let label = e.raw.type || "";
      if (e.raw.redacted) {
        label = `[RESTRICTED]${e.raw.required_permission ? " " + e.raw.required_permission : ""}`;
      }
      text.textContent = label;
    }

    for (const n of nodes) {
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("transform", `translate(${n.x},${n.y})`);
      g.style.cursor = "grab";
      g.dataset.nodeId = String(n.id);

      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("r", String(n.r));
      circle.setAttribute("class", n.id === rootNumericId ? "node-disc root" : "node-disc");

      const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      hit.setAttribute("r", String(n.r + 6));
      hit.setAttribute("class", "node-outline");

      const t1 = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t1.setAttribute("class", "node-label");
      t1.setAttribute("text-anchor", "middle");
      t1.setAttribute("y", "-4");
      t1.textContent = n.title;

      const t2 = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t2.setAttribute("class", "node-sub");
      t2.setAttribute("text-anchor", "middle");
      t2.setAttribute("y", "14");
      t2.textContent = n.subtitle;

      g.appendChild(hit);
      g.appendChild(circle);
      g.appendChild(t1);
      g.appendChild(t2);

      g.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        state.selectedNodeId = n.id;
        state.draggedNodeId = n.id;
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX;
        pt.y = ev.clientY;
        const ctm = svg.getScreenCTM();
        const local = pt.matrixTransform(ctm.inverse());
        state.dragOffset.x = local.x - n.x;
        state.dragOffset.y = local.y - n.y;
        g.setPointerCapture(ev.pointerId);
        g.style.cursor = "grabbing";
        updateInspector();
      });

      g.addEventListener("pointerup", (ev) => {
        if (state.draggedNodeId === n.id) {
          state.draggedNodeId = null;
        }
        g.style.cursor = "grab";
      });

      g.addEventListener("pointercancel", () => {
        if (state.draggedNodeId === n.id) state.draggedNodeId = null;
        g.style.cursor = "grab";
      });

      nodeLayer.appendChild(g);
      n.el = g;
    }

    svg.appendChild(edgeLayer);
    svg.appendChild(nodeLayer);

    startSimulation();
    fitView(state.nodes);
    updateInspector();
  }

  function updateEdgeGeometry() {
    for (const e of state.edges) {
      const s = e.source;
      const t = e.target;
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;

      const x1 = s.x + ux * s.r;
      const y1 = s.y + uy * s.r;
      const x2 = t.x - ux * t.r;
      const y2 = t.y - uy * t.r;

      e.el.setAttribute("d", `M ${x1} ${y1} L ${x2} ${y2}`);

      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2 - 10;
      const bbox = e.text.getBBox();
      const padX = 7;
      const padY = 4;
      e.bg.setAttribute("x", String(mx - bbox.width / 2 - padX));
      e.bg.setAttribute("y", String(my - bbox.height / 2 - padY));
      e.bg.setAttribute("width", String(bbox.width + padX * 2));
      e.bg.setAttribute("height", String(bbox.height + padY * 2));
      e.text.setAttribute("x", String(mx));
      e.text.setAttribute("y", String(my + bbox.height / 4));
    }
  }

  function startSimulation() {
    if (state.simHandle) cancelAnimationFrame(state.simHandle);

    const center = { x: 520, y: 360 };
    const iterations = 520;

    const step = () => {
      // Center pull
      for (const n of state.nodes) {
        n.vx += (center.x - n.x) * 0.00035;
        n.vy += (center.y - n.y) * 0.00035;
      }

      // Edge springs
      for (const e of state.edges) {
        const s = e.source;
        const t = e.target;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.hypot(dx, dy) || 1;
        const rest = 190;
        const force = (dist - rest) * 0.012;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        s.vx += fx;
        s.vy += fy;
        t.vx -= fx;
        t.vy -= fy;
      }

      // Repulsion
      for (let i = 0; i < state.nodes.length; i += 1) {
        for (let j = i + 1; j < state.nodes.length; j += 1) {
          const a = state.nodes[i];
          const b = state.nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist2 = dx * dx + dy * dy + 1;
          const rep = 5200 / dist2;
          const len = Math.sqrt(dist2);
          const fx = (dx / len) * rep;
          const fy = (dy / len) * rep;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      // Integrate + damping
      for (const n of state.nodes) {
        if (state.draggedNodeId === n.id) {
          n.vx = 0;
          n.vy = 0;
        } else {
          n.x += n.vx;
          n.y += n.vy;
          n.vx *= 0.88;
          n.vy *= 0.88;
        }
        n.el.setAttribute("transform", `translate(${n.x},${n.y})`);
      }

      updateEdgeGeometry();

      if (iterations-- > 0) {
        state.simHandle = requestAnimationFrame(step);
      }
    };

    state.simHandle = requestAnimationFrame(step);
  }

  svg.addEventListener("pointermove", (ev) => {
    if (!state.draggedNodeId) return;
    const n = state.nodes.find((item) => item.id === state.draggedNodeId);
    if (!n) return;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const ctm = svg.getScreenCTM();
    const local = pt.matrixTransform(ctm.inverse());
    n.x = local.x - state.dragOffset.x;
    n.y = local.y - state.dragOffset.y;
    n.vx = 0;
    n.vy = 0;
    n.el.setAttribute("transform", `translate(${n.x},${n.y})`);
    updateEdgeGeometry();
  });

  function updateInspector() {
    const selected = state.nodes.find((n) => n.id === state.selectedNodeId);
    if (!selected) {
      inspectorBody.textContent = "Select a node to inspect permission-filtered properties.";
      return;
    }
    const pretty = JSON.stringify(selected.raw, null, 2);
    inspectorBody.textContent = pretty;
  }

  async function loadGraph() {
    const agentId = agentIdEl.value.trim();
    const root = rootKeyEl.value.trim();
    const depth = Number(depthEl.value || 2);

    if (!agentId || !root) {
      setStatus("agent id and root node key are required.");
      return;
    }

    syncUrlFromInputs({ replace: false });
    setStatus("Loading…");

    const params = new URLSearchParams();
    params.set("agent_id", agentId);
    params.set("root", root);
    params.set("depth", String(depth));
    if (ignoreEdgeAclEl.checked) params.set("ignore_edge_acl", "1");
    if (hideRedactedEdgesEl.checked) params.set("hide_redacted_edges", "1");

    const res = await fetch(`/api/graph?${params.toString()}`);
    const payload = await res.json();
    if (!res.ok) {
      setStatus(`Error: ${payload.error || res.statusText}`);
      return;
    }

    setStatus(
      `Loaded ${payload.nodes.length} nodes, ${payload.edges.length} edges for agent "${agentId}".`,
    );
    renderGraph(payload);
  }

  loadBtn.addEventListener("click", () => {
    loadGraph();
  });

  window.addEventListener("popstate", () => {
    applyQueryDefaults();
    loadGraph();
  });

  applyQueryDefaults();
  if (rootKeyEl.value) {
    loadGraph();
  } else {
    setStatus('Set a root node key (for example "person:jane") and click Load graph.');
  }
})();
