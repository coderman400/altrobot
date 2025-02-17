import { useState, useEffect } from "react";
import axios from "axios";
import {FileUp ,Upload, Loader2} from 'lucide-react'
import Navbar from "./Navbar";
import Info from "./Info";
const App = () => {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState("");

  useEffect(() => {
    const wakeupBackend = async () => {
      try {
        const response = await axios.get('https://krbala.pythonanywhere.com/wakeup');
        console.log(response.data.message);  // Logs the wake-up message
      } catch (error) {
        console.error('Error waking up the backend:', error);
      }
    };

    wakeupBackend();
  }, []);
// Handle file selection
  const handleFileChange = (event) => {
    const selectedFile = event.target.files[0];
    
    // Validate if the file is a .docx
    if (selectedFile && selectedFile.name.toLowerCase().endsWith('.docx')) {
      setFile(selectedFile);
      setDownloadUrl(""); // Reset previous downloads
    } else {
      alert("Please select a .docx file.");
      setFile(null);  // Clear file if it's not .docx
    }
  };

  // Handle file upload
  const handleUpload = async () => {
    if (!file) {
      alert("Please select a .docx file.");
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post("https://krbala.pythonanywhere.com/upload_pdf", formData, {
        responseType: "blob", 
      });
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
    <>
    <Navbar />
    <div className=" flex flex-col items-center">
      <div className="mt-20">
        <h1 className="text-3xl text-center font-libre tracking-wider">Draft approved? Just drop the .docx</h1>
        <div className="space-y-4 mt-16 px-8 font-libre">
          <label
            htmlFor="fileInput"
            className={`border-2 border-dashed bg-[#3d3d3a] text-text rounded-lg p-16 flex flex-col items-center justify-center cursor-pointer transition-colors ${
              file ? "bg-green-950 opacity-50" : "hover:bg-gray-50 dark:hover:bg-gray-700"
            }`}
          >
            {file ? (
              <>
                <FileUp className="w-12 h-12 text-green-500 mb-2" />
                <p className="text-sm font-medium text-green-600 dark:text-green-400">{file.name}</p>
              </>
            ) : (
              <>
                <FileUp className="w-12 h-12 mb-2" />
                <p className="text-sm font-medium ">Click or drag to upload .docx</p>
              </>
            )}
          </label>
          <input type="file" id="fileInput" accept=".docx" onChange={handleFileChange} className="hidden" />
          {file && (
            <button
              onClick={handleUpload}
              disabled={loading}
              className="w-full py-3 px-4 bg-[#5f51a1] hover:bg-[#4b3f7e] hover:cursor-pointer text-white font-semibold rounded-lg shadow-md focus:outline-none focus:ring-2 focus:ring-opacity-75 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 inline animate-spin" />
                  Processing...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 mr-2 inline" />
                  Upload DOCX
                </>
              )}
            </button>
          )}
          {downloadUrl && (
            <a
              href={downloadUrl}
              download="compressed_results.zip"
              className="block w-full py-3 px-4 bg-text text-dark-100 hover:bg-[#c4816b] font-semibold rounded-lg shadow-md focus:outline-none focus:ring-2 focus:ring-opacity-75 transition-colors text-center"
            >
              Download Compressed ZIP
            </a>
          )}
          </div>
        </div>
    </div>
    <Info />
    </>
  );
};

export default App;
