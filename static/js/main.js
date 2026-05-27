(function () {
  "use strict";

  // ── Tab navigation ────────────────────────────
  const navItems = document.querySelectorAll(".nav-item");
  const panels   = document.querySelectorAll(".panel");

  function setActivePanel(id) {
    panels.forEach(p => p.classList.toggle("active", p.id === id));
    navItems.forEach(n => {
      const on = n.dataset.target === id;
      n.classList.toggle("active", on);
      n.setAttribute("aria-selected", String(on));
    });
  }
  navItems.forEach(n => n.addEventListener("click", () => setActivePanel(n.dataset.target)));


  // ── History (localStorage) ────────────────────
  const HISTORY_KEY = "ial_history";
  const HISTORY_MAX = 10;

  function historyLoad() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); }
    catch { return []; }
  }
  function historySave(arr) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr)); } catch {}
  }
  function historyAdd(entry) {
    const arr = historyLoad();
    arr.unshift(entry);
    historySave(arr.slice(0, HISTORY_MAX));
    renderHistory();
  }
  function esc(s) {
    return String(s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;")
      .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function renderHistory() {
    const list  = document.getElementById("historyList");
    const items = historyLoad();
    if (!items.length) {
      list.innerHTML = '<div class="history-empty">No analyses yet</div>';
      return;
    }
    list.innerHTML = items.map(it => {
      const ll = (it.label || "").toLowerCase().replace(/\s+/g,"-");
      const cls = ll.includes("tampered") ? "tampered"
                : ll.includes("ai") || ll.includes("generated") ? "ai-generated"
                : ll.includes("real") ? "real" : "unknown";
      const ts = it.timestamp
        ? new Date(it.timestamp).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})
        : "";
      return `<div class="history-item">
        <div class="history-item-name" title="${esc(it.fileName)}">${esc(it.fileName)}</div>
        <div class="history-item-meta">
          <span class="history-label ${cls}">${esc(it.label||"—")}</span>
          <span class="history-time">${ts}</span>
        </div>
      </div>`;
    }).join("");
  }
  document.getElementById("historyClear").addEventListener("click", () => {
    historySave([]); renderHistory();
  });
  renderHistory();


  // ── Per-uploader ──────────────────────────────
  document.querySelectorAll(".uploader").forEach(root => {
    const mode       = root.dataset.mode;
    const dropzone   = root.querySelector("[data-dropzone]");
    const fileInput  = root.querySelector("[data-file]");
    const browse     = root.querySelector("[data-browse]");
    const btnProcess = root.querySelector("[data-process]");
    const btnClear   = root.querySelector("[data-clear]");
    const btnReport  = root.querySelector("[data-report]");
    const statusEl      = root.querySelector("[data-status]");
    const resultsWrap   = root.querySelector("[data-results]");
    // ELA sweep elements (only present in the forgery uploader)
    const elaSweepCard  = root.querySelector("[data-ela-sweep-card]");
    const elaSweepGrid  = root.querySelector("[data-ela-sweep-grid]");

    // Small thumb shown after file pick
    const thumbWrap  = root.querySelector("[data-preview-thumb]");
    const thumbImg   = root.querySelector("[data-thumb-img]");
    const thumbName  = root.querySelector("[data-thumb-name]");
    const thumbSize  = root.querySelector("[data-thumb-size]");

    // Result fields
    const elLabel    = root.querySelector("[data-label]");
    const elMeter    = root.querySelector("[data-meter]");
    const elConf     = root.querySelector("[data-confidence]");
    const elCapImg   = root.querySelector("[data-caption-image]");
    const elCapOut   = root.querySelector("[data-caption-output]");
    const metaCard   = root.querySelector("[data-metadata-card]");
    const metaTable  = root.querySelector("[data-meta-table]");

    // Image card states
    const stateImage  = root.querySelector("[data-state-image]");
    const displayImg  = root.querySelector("[data-display-img]");
    const stateSlider = root.querySelector("[data-state-slider]");   // null for AI tab
    const sliderWrap  = root.querySelector("[data-slider-wrap]");
    const sliderBase  = root.querySelector("[data-slider-base]");
    const sliderHeat  = root.querySelector("[data-slider-heatmap]");
    const sliderOvr   = root.querySelector("[data-slider-overlay]");
    const sliderHnd   = root.querySelector("[data-slider-handle]");

    let currentFile    = null;
    let currentFileURL = null;
    let lastResult     = null;
    let sliderReady    = false;

    // ── status ──
    function setStatus(msg, isError = false) {
      if (!msg) { statusEl.hidden = true; return; }
      statusEl.hidden = false;
      statusEl.textContent = msg;
      statusEl.className = "status" + (isError ? " error" : "");
    }

    // ── reset ──
    function resetUI() {
      currentFile = lastResult = null;
      if (currentFileURL) { URL.revokeObjectURL(currentFileURL); currentFileURL = null; }
      fileInput.value = "";
      btnProcess.disabled = btnClear.disabled = true;
      if (btnReport) btnReport.disabled = true;
      if (thumbWrap) thumbWrap.hidden = true;
      resultsWrap.hidden = true;
      // Reset image card to plain state
      if (stateImage)  stateImage.hidden  = false;
      if (stateSlider) stateSlider.hidden = true;
      if (elaSweepCard) elaSweepCard.hidden = true;
      sliderReady = false;
      setStatus("");
    }

    // ── file picked ──
    function setFile(file) {
      currentFile = file;
      lastResult  = null;
      sliderReady = false;
      btnProcess.disabled = false;
      btnClear.disabled   = false;
      if (btnReport) btnReport.disabled = true;

      if (currentFileURL) URL.revokeObjectURL(currentFileURL);
      currentFileURL = URL.createObjectURL(file);

      // Show tiny thumbnail below dropzone
      if (thumbWrap) {
        thumbImg.src = currentFileURL;
        thumbName.textContent = file.name;
        thumbSize.textContent = formatBytes(file.size);
        thumbWrap.hidden = false;
      }

      // Hide results entirely until processing finishes
      resultsWrap.hidden = true;
      if (stateImage)  stateImage.hidden  = false;
      if (stateSlider) stateSlider.hidden = true;
      if (elaSweepCard) elaSweepCard.hidden = true;
      setStatus("");
    }

    function formatBytes(b) {
      return b >= 1048576 ? (b/1048576).toFixed(1)+" MB" : (b/1024).toFixed(0)+" KB";
    }

    // ── file input wiring ──
    browse.addEventListener("click", e => { e.preventDefault(); fileInput.click(); });
    fileInput.addEventListener("change", () => {
      const f = fileInput.files && fileInput.files[0];
      if (f) setFile(f);
    });
    dropzone.addEventListener("click", () => fileInput.click());
    ["dragenter","dragover"].forEach(ev =>
      dropzone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); dropzone.classList.add("dragover"); })
    );
    ["dragleave","drop"].forEach(ev =>
      dropzone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove("dragover"); })
    );
    dropzone.addEventListener("drop", e => {
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      if (!/image\/(jpeg|png)/.test(f.type)) { setStatus("Only JPG/PNG files are supported.", true); return; }
      setFile(f);
    });
    btnClear.addEventListener("click", resetUI);

    // ── Slider logic ──
    function initSlider() {
      if (!sliderWrap) return;
      let dragging = false;

      function setPct(pct) {
        pct = Math.max(0, Math.min(100, pct));
        sliderOvr.style.width = pct + "%";
        sliderHnd.style.left  = pct + "%";
        // The heatmap image must be as wide as the container so it stays aligned
        if (sliderBase.naturalWidth > 0) {
          const displayW = sliderWrap.offsetWidth;
          const displayH = sliderBase.offsetHeight;
          sliderHeat.style.width  = displayW + "px";
          sliderHeat.style.height = displayH + "px";
        }
      }

      function onMove(clientX) {
        const r = sliderWrap.getBoundingClientRect();
        setPct(((clientX - r.left) / r.width) * 100);
      }

      sliderWrap.addEventListener("mousedown",  e => { dragging = true; onMove(e.clientX); });
      window.addEventListener    ("mousemove",  e => { if (dragging) onMove(e.clientX); });
      window.addEventListener    ("mouseup",    ()  => { dragging = false; });
      sliderWrap.addEventListener("touchstart", e => { dragging = true; onMove(e.touches[0].clientX); }, {passive:true});
      window.addEventListener    ("touchmove",  e => { if (dragging) onMove(e.touches[0].clientX); }, {passive:true});
      window.addEventListener    ("touchend",   ()  => { dragging = false; });

      // Re-initialise position once base image loads (its dimensions are needed)
      sliderBase.addEventListener("load", () => { setPct(50); sliderReady = true; }, {once:true});
    }
    if (mode === "forgery") initSlider();

    // ── Metadata render ──
    const META_LABELS = {
      file_name:"File Name", file_size:"File Size", format:"Format",
      mode:"Color Mode", resolution:"Resolution",
      camera_make:"Camera Make", camera_model:"Camera Model",
      software:"Software", capture_date:"Capture Date",
      focal_length:"Focal Length", f_number:"F-Number",
      exposure_time:"Exposure Time", iso:"ISO", flash:"Flash",
      gps_coordinates:"GPS Coordinates",
    };
    function renderMetadata(meta) {
      if (!metaTable || !metaCard) return;
      const tbody = metaTable.querySelector("tbody");
      tbody.innerHTML = "";
      let n = 0;
      for (const [k, v] of Object.entries(meta || {})) {
        if (k === "exif_error" || k === "exif_width" || k === "exif_height") continue;
        const label = META_LABELS[k] || k.replace(/_/g," ").replace(/\b\w/g, c=>c.toUpperCase());
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(label)}</td><td>${esc(String(v))}</td>`;
        tbody.appendChild(tr);
        n++;
      }
      metaCard.hidden = n === 0;
    }

    // ── Process ──
    async function process() {
      if (!currentFile) return;
      btnProcess.disabled = btnClear.disabled = true;
      if (btnReport) btnReport.disabled = true;
      setStatus("Processing… this may take a moment on first run.");

      const fd = new FormData();
      fd.append("image", currentFile);
      const endpoint = mode === "forgery" ? "/api/forgery-detect" : "/api/ai-classify";

      try {
        const res  = await fetch(endpoint, { method:"POST", body:fd });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "Request failed.");

        // ── Populate result fields ──
        elLabel.textContent = data.label || "—";

        const pct = typeof data.confidence_percent === "number"
          ? data.confidence_percent
          : Math.round((data.confidence || 0) * 100);
        elConf.textContent    = pct.toFixed(1) + "%";
        elMeter.style.width   = Math.max(0, Math.min(100, pct)) + "%";
        elCapImg.textContent  = data.caption_image  || "—";
        elCapOut.textContent  = data.caption_output || "—";

        renderMetadata(data.metadata);

        // ── Show image area ──
        if (mode === "forgery" && stateSlider && data.heatmap_url) {
          // Swap plain image out, bring slider in
          const ts = "?v=" + Date.now();
          sliderBase.src = data.uploaded_image_url + ts;
          sliderHeat.src = data.heatmap_url        + ts;
          stateImage.hidden  = true;
          stateSlider.hidden = false;
          // Set to 50% after base loads (handled in load listener above)
        } else {
          // AI tab: just show the uploaded image normally
          displayImg.src    = data.uploaded_image_url || currentFileURL;
          stateImage.hidden = false;
        }

        // ── ELA quality sweep (forgery only) ──────────────────────────
        if (mode === "forgery" && elaSweepCard && elaSweepGrid
            && Array.isArray(data.ela_sweep) && data.ela_sweep.length) {
          elaSweepGrid.innerHTML = data.ela_sweep.map(s => `
            <div class="ela-sweep-item">
              <img src="data:image/png;base64,${s.b64}"
                   alt="ELA q=${s.quality}" loading="lazy" />
              <div class="ela-sweep-badge">q=${s.quality}</div>
            </div>
          `).join("");
          elaSweepCard.hidden = false;
        }

        // ── Reveal results grid ──
        resultsWrap.hidden = false;

        // ── History ──
        historyAdd({
          fileName:  currentFile.name,
          label:     data.label || "—",
          task:      mode,
          timestamp: Date.now(),
        });

        lastResult = data;
        if (btnReport) btnReport.disabled = false;
        setStatus("Analysis complete.");

      } catch (err) {
        console.error(err);
        setStatus(err.message || "Something went wrong.", true);
      } finally {
        btnProcess.disabled = btnClear.disabled = false;
      }
    }

    btnProcess.addEventListener("click", process);

    // ── Report download ──
    async function downloadReport() {
      if (!lastResult) return;
      try {
        if (btnReport) btnReport.disabled = true;
        setStatus("Generating PDF report…");

        const payload = {
          task:               mode,
          uploaded_image_url: lastResult.uploaded_image_url,
          heatmap_url:        lastResult.heatmap_url || null,
          label:              lastResult.label,
          confidence:         lastResult.confidence,
          confidence_percent: lastResult.confidence_percent,
          caption_image:      lastResult.caption_image,
          caption_output:     lastResult.caption_output,
          // ela_sweep is regenerated server-side — not sent over the network
        };
        const res = await fetch("/api/report", {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify(payload),
        });
        if (!res.ok) {
          const j = await res.json().catch(()=>null);
          throw new Error((j&&j.error) || "Failed to generate report.");
        }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement("a");
        a.href = url;
        a.download = `report-${mode}-${new Date().toISOString().replace(/[:.]/g,"-")}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setStatus("Report downloaded.");
      } catch (err) {
        console.error(err);
        setStatus(err.message || "Could not download report.", true);
      } finally {
        if (btnReport) btnReport.disabled = !lastResult;
      }
    }
    if (btnReport) btnReport.addEventListener("click", downloadReport);

    resetUI();
  });

})();
