import { useState, useCallback, useRef } from "react";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CODEC_COLORS = {
  Opus: "#7c3aed",
  AAC: "#0369a1",
  MP3: "#15803d",
  Vorbis: "#b45309",
  FLAC: "#be123c",
  WAV: "#475569",
};

function codecColor(codec) {
  return CODEC_COLORS[codec] || "#6b7280";
}

function formatBytes(mb) {
  if (!mb) return "";
  if (mb < 1) return `~${Math.round(mb * 1024)} KB`;
  return `~${mb.toFixed(1)} MB`;
}

// ─── API calls ───────────────────────────────────────────────────────────────

async function apiAnalyze(url) {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Analysis failed.");
  return data;
}

async function apiStartDownload(url, format, mp3Bitrate) {
  const body = { url, format };
  if (format === "mp3") body.mp3_bitrate = mp3Bitrate;
  const res = await fetch(`${API_BASE}/download/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Download start failed.");
  return data;
}

async function apiPollStatus(jobId) {
  const res = await fetch(`${API_BASE}/download/status/${jobId}`);
  return res.json();
}

// ─── Components ──────────────────────────────────────────────────────────────

function Badge({ children, color }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        background: color + "22",
        color: color,
        border: `1px solid ${color}44`,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: 0.5,
        fontFamily: "monospace",
      }}
    >
      {children}
    </span>
  );
}

function StreamCard({ stream }) {
  const color = codecColor(stream.codec);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 8,
        background: stream.is_best ? color + "11" : "#f8f9fa",
        border: `1px solid ${stream.is_best ? color + "44" : "#e5e7eb"}`,
        position: "relative",
      }}
    >
      <Badge color={color}>{stream.codec}</Badge>
      <span style={{ fontWeight: 700, fontSize: 14, color: "#111" }}>
        {stream.bitrate} kbps
      </span>
      <span style={{ fontSize: 12, color: "#6b7280", fontFamily: "monospace" }}>
        .{stream.format}
      </span>
      {stream.size_estimate_mb && (
        <span style={{ fontSize: 12, color: "#9ca3af", marginLeft: "auto" }}>
          {formatBytes(stream.size_estimate_mb)}
        </span>
      )}
      {stream.is_best && (
        <span
          style={{
            marginLeft: stream.size_estimate_mb ? 0 : "auto",
            fontSize: 11,
            fontWeight: 700,
            color,
            background: color + "18",
            padding: "2px 8px",
            borderRadius: 4,
          }}
        >
          ★ Best Available
        </span>
      )}
    </div>
  );
}

function ProgressBar({ value }) {
  return (
    <div
      style={{
        height: 6,
        borderRadius: 3,
        background: "#e5e7eb",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${value}%`,
          height: "100%",
          background: "linear-gradient(90deg, #7c3aed, #0369a1)",
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}

function DownloadButton({ label, sublabel, onClick, disabled, variant = "secondary" }) {
  const isPrimary = variant === "primary";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "10px 16px",
        borderRadius: 8,
        border: `1px solid ${isPrimary ? "#7c3aed" : "#d1d5db"}`,
        background: isPrimary ? "#7c3aed" : "#fff",
        color: isPrimary ? "#fff" : "#374151",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        textAlign: "left",
        width: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        transition: "all 0.15s",
      }}
    >
      <span style={{ fontWeight: 600, fontSize: 14 }}>{label}</span>
      {sublabel && (
        <span
          style={{
            fontSize: 11,
            color: isPrimary ? "rgba(255,255,255,0.8)" : "#9ca3af",
            whiteSpace: "nowrap",
          }}
        >
          {sublabel}
        </span>
      )}
    </button>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | analyzing | ready | downloading | done | error
  const [analysis, setAnalysis] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [job, setJob] = useState(null);
  const [downloadedFile, setDownloadedFile] = useState(null);
  const pollRef = useRef(null);

  const reset = useCallback(() => {
    clearInterval(pollRef.current);
    setPhase("idle");
    setAnalysis(null);
    setErrorMsg("");
    setJob(null);
    setDownloadedFile(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!url.trim()) return;
    clearInterval(pollRef.current);
    setPhase("analyzing");
    setAnalysis(null);
    setErrorMsg("");
    setJob(null);
    setDownloadedFile(null);
    try {
      const data = await apiAnalyze(url.trim());
      setAnalysis(data);
      setPhase("ready");
    } catch (e) {
      setErrorMsg(e.message);
      setPhase("error");
    }
  }, [url]);

  const handleDownload = useCallback(
    async (format, mp3Bitrate = null) => {
      setPhase("downloading");
      setErrorMsg("");
      setDownloadedFile(null);
      try {
        const jobData = await apiStartDownload(url.trim(), format, mp3Bitrate);
        setJob(jobData);

        // Poll status
        pollRef.current = setInterval(async () => {
          try {
            const status = await apiPollStatus(jobData.job_id);
            setJob(status);
            if (status.status === "done") {
              clearInterval(pollRef.current);
              setDownloadedFile(status.download_url);
              setPhase("done");
            } else if (status.status === "error") {
              clearInterval(pollRef.current);
              setErrorMsg(status.error || "Download failed.");
              setPhase("error");
            }
          } catch (_) {}
        }, 1000);
      } catch (e) {
        setErrorMsg(e.message);
        setPhase("error");
      }
    },
    [url]
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#f9fafb",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "40px 16px 80px",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      }}
    >
      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 36 }}>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: "#111827",
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          YouTube Audio Downloader
        </h1>
        <p style={{ color: "#6b7280", marginTop: 8, fontSize: 14 }}>
          Detects actual source quality. Never offers upscaled audio.
        </p>
      </div>

      {/* URL Input */}
      <div
        style={{
          width: "100%",
          maxWidth: 560,
          display: "flex",
          gap: 10,
          marginBottom: 32,
        }}
      >
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
          placeholder="Paste a YouTube URL…"
          disabled={phase === "analyzing" || phase === "downloading"}
          style={{
            flex: 1,
            padding: "12px 16px",
            borderRadius: 8,
            border: "1.5px solid #d1d5db",
            fontSize: 14,
            outline: "none",
            background: "#fff",
            color: "#111",
          }}
        />
        <button
          onClick={handleAnalyze}
          disabled={!url.trim() || phase === "analyzing" || phase === "downloading"}
          style={{
            padding: "12px 20px",
            borderRadius: 8,
            border: "none",
            background: "#111827",
            color: "#fff",
            fontWeight: 700,
            fontSize: 14,
            cursor: "pointer",
            whiteSpace: "nowrap",
            opacity:
              !url.trim() || phase === "analyzing" || phase === "downloading"
                ? 0.5
                : 1,
          }}
        >
          {phase === "analyzing" ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {/* Main card */}
      <div style={{ width: "100%", maxWidth: 560 }}>
        {/* Error */}
        {phase === "error" && (
          <div
            style={{
              padding: 16,
              borderRadius: 10,
              background: "#fef2f2",
              border: "1px solid #fecaca",
              color: "#991b1b",
              fontSize: 14,
              marginBottom: 16,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
            }}
          >
            <span>{errorMsg}</span>
            <button
              onClick={reset}
              style={{
                background: "none",
                border: "none",
                color: "#991b1b",
                cursor: "pointer",
                fontWeight: 700,
                fontSize: 16,
                lineHeight: 1,
                marginLeft: 12,
                flexShrink: 0,
              }}
            >
              ✕
            </button>
          </div>
        )}

        {/* Analysis results */}
        {(phase === "ready" || phase === "downloading" || phase === "done") &&
          analysis && (
            <div
              style={{
                background: "#fff",
                borderRadius: 12,
                border: "1px solid #e5e7eb",
                overflow: "hidden",
              }}
            >
              {/* Video info */}
              <div
                style={{
                  padding: "16px 20px",
                  borderBottom: "1px solid #f3f4f6",
                  display: "flex",
                  gap: 14,
                  alignItems: "flex-start",
                }}
              >
                {analysis.thumbnail && (
                  <img
                    src={analysis.thumbnail}
                    alt=""
                    style={{
                      width: 72,
                      height: 54,
                      objectFit: "cover",
                      borderRadius: 6,
                      flexShrink: 0,
                    }}
                  />
                )}
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 700,
                      fontSize: 15,
                      color: "#111",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={analysis.title}
                  >
                    {analysis.title}
                  </div>
                  <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                    {analysis.channel} · {analysis.duration}
                  </div>
                </div>
              </div>

              {/* Source quality */}
              <div
                style={{
                  padding: "14px 20px",
                  borderBottom: "1px solid #f3f4f6",
                  background: "#fafafa",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: 1,
                    color: "#9ca3af",
                    textTransform: "uppercase",
                    marginBottom: 8,
                  }}
                >
                  Source Audio
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <Badge color={codecColor(analysis.best_quality.codec)}>
                    {analysis.best_quality.codec}
                  </Badge>
                  <span style={{ fontWeight: 700, fontSize: 18, color: "#111" }}>
                    {analysis.best_quality.bitrate} kbps
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      color: "#6b7280",
                      fontFamily: "monospace",
                    }}
                  >
                    .{analysis.best_quality.format}
                  </span>
                  {!analysis.can_offer_320 && (
                    <span
                      style={{
                        fontSize: 11,
                        color: "#92400e",
                        background: "#fef3c7",
                        padding: "2px 8px",
                        borderRadius: 4,
                        border: "1px solid #fde68a",
                      }}
                    >
                      320 kbps not available
                    </span>
                  )}
                </div>
              </div>

              {/* All streams */}
              <div
                style={{
                  padding: "14px 20px",
                  borderBottom: "1px solid #f3f4f6",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: 1,
                    color: "#9ca3af",
                    textTransform: "uppercase",
                    marginBottom: 8,
                  }}
                >
                  All Audio Streams Detected
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {analysis.audio_streams.map((s, i) => (
                    <StreamCard key={i} stream={s} />
                  ))}
                </div>
              </div>

              {/* Download options */}
              {phase === "ready" && (
                <div style={{ padding: "14px 20px" }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: 1,
                      color: "#9ca3af",
                      textTransform: "uppercase",
                      marginBottom: 10,
                    }}
                  >
                    Download Options
                  </div>

                  {/* Original */}
                  <div style={{ marginBottom: 8 }}>
                    <DownloadButton
                      variant="primary"
                      label={`✓ Original Audio (Recommended)`}
                      sublabel={`${analysis.best_quality.codec} · ${analysis.best_quality.bitrate} kbps · .${analysis.best_quality.format}`}
                      onClick={() => handleDownload("original")}
                    />
                    <div
                      style={{
                        fontSize: 11,
                        color: "#6b7280",
                        marginTop: 4,
                        paddingLeft: 2,
                      }}
                    >
                      No quality loss · Fastest · Preserves original codec
                    </div>
                  </div>

                  {/* MP3 options */}
                  {analysis.allowed_mp3_options.length > 0 && (
                    <>
                      <div
                        style={{
                          fontSize: 12,
                          color: "#374151",
                          fontWeight: 600,
                          margin: "12px 0 6px",
                        }}
                      >
                        MP3 Conversion
                      </div>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr",
                          gap: 6,
                        }}
                      >
                        {analysis.allowed_mp3_options.map((kbps) => (
                          <DownloadButton
                            key={kbps}
                            label={`MP3 ${kbps} kbps`}
                            sublabel={kbps === analysis.allowed_mp3_options[0] ? "Highest" : ""}
                            onClick={() => handleDownload("mp3", kbps)}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {/* Quality note */}
                  <div
                    style={{
                      marginTop: 14,
                      padding: "10px 14px",
                      background: "#f0f9ff",
                      borderRadius: 8,
                      border: "1px solid #bae6fd",
                      fontSize: 12,
                      color: "#0369a1",
                      lineHeight: 1.5,
                    }}
                  >
                    ℹ {analysis.quality_note}
                  </div>
                </div>
              )}

              {/* Download progress */}
              {phase === "downloading" && job && (
                <div style={{ padding: "20px" }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 8,
                      fontSize: 13,
                    }}
                  >
                    <span style={{ color: "#374151", fontWeight: 600 }}>
                      {job.status === "pending"
                        ? "Queued…"
                        : job.status === "processing"
                        ? "Downloading & converting…"
                        : job.status}
                    </span>
                    <span style={{ color: "#6b7280" }}>{job.progress}%</span>
                  </div>
                  <ProgressBar value={job.progress} />
                </div>
              )}

              {/* Done */}
              {phase === "done" && downloadedFile && (
                <div style={{ padding: "20px" }}>
                  <a
                    href={downloadedFile}
                    download
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 20px",
                      borderRadius: 8,
                      background: "#15803d",
                      color: "#fff",
                      textDecoration: "none",
                      fontWeight: 700,
                      fontSize: 15,
                    }}
                  >
                    ↓ Download Ready — Click to Save
                  </a>
                  <button
                    onClick={reset}
                    style={{
                      marginTop: 10,
                      width: "100%",
                      padding: "8px",
                      border: "1px solid #e5e7eb",
                      borderRadius: 8,
                      background: "#fff",
                      color: "#6b7280",
                      cursor: "pointer",
                      fontSize: 13,
                    }}
                  >
                    Download another
                  </button>
                </div>
              )}
            </div>
          )}
      </div>
    </div>
  );
}
