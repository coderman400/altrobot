import { useState } from "react";
import axios from "axios";

const App = () => {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState("");

  // Handle file selection
  const handleFileChange = (event) => {
    setFile(event.target.files[0]);
    setDownloadUrl(""); // Reset previous downloads
  };

  // Handle file upload
  const handleUpload = async () => {
    if (!file) {
      alert("Please select a PDF file.");
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post("http://127.0.0.1:8000/upload_pdf/", formData, {
        responseType: "blob", // Get binary data (ZIP file)
      });

      // Create a download link for the ZIP file
      const url = window.URL.createObjectURL(new Blob([response.data]));
      setDownloadUrl(url);
    } catch (error) {
      console.error("Error uploading file:", error);
      alert("Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center p-4 border rounded-lg shadow-md max-w-md mx-auto">
      <input
        type="file"
        accept="application/pdf"
        onChange={handleFileChange}
        className="mb-4 border p-2 rounded"
      />
      <button
        onClick={handleUpload}
        className="bg-blue-500 text-white px-4 py-2 rounded disabled:opacity-50"
        disabled={loading}
      >
        {loading ? "Uploading..." : "Upload PDF"}
      </button>

      {downloadUrl && (
        <a
          href={downloadUrl}
          download="compressed_results.zip"
          className="mt-4 text-green-600 underline"
        >
          Download Compressed ZIP
        </a>
      )}
    </div>
  );
};

export default App;
