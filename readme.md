# 📄 Altrobot 

A web application that processes `.docx` files to:  
✅ Extract images and GIFs  
✅ Compress them to a specified size  
✅ Generate alt texts using Google Gemini AI  
✅ Bundle everything into a downloadable `.zip`  

##  Tech Stack  
- **Frontend:** React, Tailwind CSS  
- **Backend:** FastAPI  
- **AI Integration:** Google Gemini API  

---

##  Features  

1. **📄 Upload a `.docx` file**  
   - Extracts all images and GIFs from the document.  

2. **📉 Compress Images & GIFs**  
   - JPG/PNG compressed to a target size (default: `100KB`).  
   - GIFs optimized with reduced colors and adaptive palette.  

3. **🤖 Generate Alt Texts**  
   - Uses Gemini AI to generate descriptive alt texts for each image.  

4. **📦 Download Processed Files**  
   - Images & alt texts are packaged into a `.zip` file for download.  

---

##  Setup Instructions  

### **1️⃣ Backend (FastAPI)**
#### **Prerequisites:**  
- Python 3.9+  
- Install dependencies:  

```bash
pip install -r requirements.txt
```
.env File (Google Gemini API Key)

Create a .env file in the root directory:

API_KEY=your_google_gemini_api_key

