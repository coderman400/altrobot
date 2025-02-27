import os
import pytest
from main import extract_images_from_docx, get_alt_texts, TEXT_DIR, IMAGE_DIR
from tqdm import tqdm

DOCS_DIRECTORY = "docs"

def clean_directory(directory):
    """Remove all files in a given directory."""
    if os.path.exists(directory):
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    print(f"Warning: Failed to delete {file_path}: {e}")

def get_docx_files(directory):
    """Get all DOCX files in the specified directory."""
    if not os.path.exists(directory):
        return []
    return [
        os.path.join(directory, filename)
        for filename in os.listdir(directory)
        if filename.lower().endswith('.docx')
    ]

@pytest.mark.parametrize("docx_file", get_docx_files(DOCS_DIRECTORY))
def test_image_alt_text_count_match(docx_file):
    """Test that the number of extracted images matches the number of alt texts for each DOCX file."""
    
    clean_directory(IMAGE_DIR)
    clean_directory(TEXT_DIR)

    with open(docx_file, 'rb') as file:
        docx_bytes = file.read()

    print(docx_file)
    print("READ FILE!")

    image_paths = extract_images_from_docx(docx_bytes)
    assert image_paths, f"No images extracted from {docx_file}"
    print("IMAGES GOTTED!")

    alt_texts = get_alt_texts(image_paths,docx_file)
    for img_path, alt_text in alt_texts.items():
        txt_filename = os.path.join(TEXT_DIR, f"{os.path.splitext(os.path.basename(img_path))[0]}.txt")
        with open(txt_filename, "w") as txt_file:
            txt_file.write(alt_text)

    print("ALT TEXT GOTTED!")
    image_count = len(os.listdir(IMAGE_DIR))
    alt_text_count = len(os.listdir(TEXT_DIR))

    for txt_file in os.listdir(TEXT_DIR):
        txt_path = os.path.join(TEXT_DIR, txt_file)
        with open(txt_path, 'r') as f:
            content = f.read().strip()
            assert content, f"Empty alt text found in {txt_file} for document {os.path.basename(docx_file)}"

    assert image_count == alt_text_count, (
        f"For {docx_file}: Image count ({image_count}) doesn't match alt text count ({alt_text_count})"
    )

    print(f"✅ {os.path.basename(docx_file)}: {image_count} images, {alt_text_count} alt texts")
