import { FileText, FolderOpen, Globe2, ShieldCheck, Sparkles, Type, Upload, UploadCloud } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";

import { ApiError, uploadDocument } from "../../api";
import { InlineAlert } from "../../components/InlineAlert";
import { COUNTRY_OPTIONS, LANGUAGE_OPTIONS } from "../../constants/options";
import { errorMessage } from "../../lib/errors";
import { formatBytes } from "../../lib/format";

type UploadMode = "file" | "text";

export function UploadEvidence({
  token,
  onUploaded,
  onAuthExpired,
}: {
  token: string;
  onUploaded: () => Promise<void>;
  onAuthExpired: () => void;
}) {
  const [mode, setMode] = useState<UploadMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [country, setCountry] = useState("");
  const [language, setLanguage] = useState("auto");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleClear() {
    setFile(null);
    setTitle("");
    setText("");
    setCountry("");
    setLanguage("auto");
    setError(null);
    setSuccess(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (mode === "file" && !file) {
      setError("Select a PDF, TXT, or DOCX file.");
      return;
    }
    if (mode === "text" && (!title.trim() || !text.trim())) {
      setError("Direct text requires a title and evidence text.");
      return;
    }
    const selectedCountry = COUNTRY_OPTIONS.find((option) => option === country);
    if (!selectedCountry) {
      setError("Select the document country.");
      return;
    }

    const formData = new FormData();
    if (mode === "file" && file) {
      formData.append("file", file);
    }
    if (mode === "text") {
      formData.append("title", title.trim());
      formData.append("text", text.trim());
    }
    formData.append("country", selectedCountry);
    if (language !== "auto") {
      formData.append("language", language);
    }

    setIsSubmitting(true);
    try {
      const uploaded = await uploadDocument(token, formData);
      setSuccess(`${uploaded.title} uploaded successfully. It will appear in the library when ready.`);
      setFile(null);
      setTitle("");
      setText("");
      setCountry("");
      setLanguage("auto");
      await onUploaded();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
        return;
      }
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleFileCandidate(candidate: File | undefined) {
    if (!candidate) {
      return;
    }
    const fileName = candidate.name.toLowerCase();
    if (!fileName.endsWith(".pdf") && !fileName.endsWith(".txt") && !fileName.endsWith(".docx")) {
      setError("Only PDF, TXT, and DOCX files are supported.");
      setFile(null);
      return;
    }
    setError(null);
    setFile(candidate);
  }

  return (
    <section className="panel upload-panel" aria-labelledby="upload-title">
      <div className="panel-heading upload-heading">
        <div>
          <p className="eyebrow">Ingestion</p>
          <h3 id="upload-title">Upload evidence</h3>
        </div>
      </div>

      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="segmented-control compact" role="tablist" aria-label="Upload mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "file"}
            className={mode === "file" ? "active" : ""}
            onClick={() => setMode("file")}
          >
            <FileText size={17} aria-hidden="true" />
            File
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "text"}
            className={mode === "text" ? "active" : ""}
            onClick={() => setMode("text")}
          >
            <Type size={17} aria-hidden="true" />
            Direct text
          </button>
        </div>

        {mode === "file" ? (
          <label
            className={`drop-zone ${isDragging ? "dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              handleFileCandidate(event.dataTransfer.files[0]);
            }}
          >
            <span className="drop-zone-icon" aria-hidden="true">
              <UploadCloud size={30} />
            </span>
            <span>{file ? file.name : "Drop a PDF, TXT, or DOCX file"}</span>
            <small>{file ? formatBytes(file.size) : "or browse from your device"}</small>
            {!file ? <em>{"Supported: PDF, TXT, DOCX \u00b7 Max 10 MB"}</em> : null}
            <span className="choose-file-button">
              <FolderOpen size={18} aria-hidden="true" />
              Choose file
            </span>
            <input
              type="file"
              accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => handleFileCandidate(event.target.files?.[0])}
            />
          </label>
        ) : (
          <div className="field-stack direct-text-panel">
            <label>
              Title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="NICE oncology assessment summary"
              />
            </label>
            <label>
              Evidence text
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Paste the evidence text to index"
                rows={9}
              />
            </label>
          </div>
        )}

        <div className="upload-assurance" aria-label="Upload safeguards">
          <span>
            <ShieldCheck size={18} aria-hidden="true" />
            Files are securely processed for evidence retrieval.
          </span>
          <span>
            <Globe2 size={18} aria-hidden="true" />
            Automatic language detection
          </span>
          <span>
            <Sparkles size={18} aria-hidden="true" />
            Source-ready evidence
          </span>
        </div>

        <div className="metadata-grid">
          <label>
            Country
            <select value={country} onChange={(event) => setCountry(event.target.value)}>
              <option value="">Select country</option>
              {COUNTRY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            Language
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error ? <InlineAlert tone="error" message={error} /> : null}
        {success ? <InlineAlert tone="success" message={success} /> : null}

        <div className="form-actions">
          <button className="icon-text-button" type="button" onClick={handleClear}>
            Clear
          </button>
          <button className="primary-button" type="submit" disabled={isSubmitting}>
            <Upload size={18} aria-hidden="true" />
            {isSubmitting ? "Uploading..." : "Upload evidence"}
          </button>
        </div>
      </form>
    </section>
  );
}
