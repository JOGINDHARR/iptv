import os
import requests
import re
import time
from urllib.parse import urljoin

# Configuration
SOURCE_PLAYLISTS_MD = "https://raw.githubusercontent.com/iptv-org/iptv/master/PLAYLISTS.md"
BASE_URL = "https://iptv-org.github.io/iptv/"
USER_REPO_URL = "https://jogindharr.github.io/iptv/"
OUTPUT_DIR = "."

def download_file(url, filename):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
    return False

def generate_readme(m3u_links):
    print("Generating README.md...")
    readme_content = "# 📺 IPTV Playlist Automation Bot\n\n"
    readme_content += f"Automated M3U playlist scraper. Updated every hour. Source: [iptv-org/iptv](https://github.com/iptv-org/iptv)\n\n"
    readme_content += f"## 🔗 GitHub Pages URL\n"
    readme_content += f"Access your playlists here: [{USER_REPO_URL}]({USER_REPO_URL})\n\n"
    
    categories = {"Main": [], "Categories": [], "Languages": [], "Regions": []}
    for link in m3u_links:
        rel_path = link.replace(BASE_URL, "")
        if "/" not in rel_path: categories["Main"].append(rel_path)
        elif rel_path.startswith("categories/"): categories["Categories"].append(rel_path)
        elif rel_path.startswith("languages/"): categories["Languages"].append(rel_path)
        elif rel_path.startswith("regions/"): categories["Regions"].append(rel_path)

    for cat, files in categories.items():
        if not files: continue
        readme_content += f"### {cat}\n"
        readme_content += "| Name | M3U Link |\n"
        readme_content += "| --- | --- |\n"
        for f in files:
            name = f.split("/")[-1].replace(".m3u", "").capitalize()
            m3u_url = f"{USER_REPO_URL}{f}"
            readme_content += f"| {name} | [`{m3u_url}`]({m3u_url}) |\n"
        readme_content += "\n"

    with open("README.md", "w") as f:
        f.write(readme_content)

def generate_index_html(m3u_links):
    print("Generating index.html...")
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPTV Playlist Bot</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #121212; color: #e0e0e0; }
        .card { background-color: #1e1e1e; border: 1px solid #333; margin-bottom: 20px; }
        .btn-primary { background-color: #bb86fc; border: none; color: #000; font-weight: bold; }
        .btn-primary:hover { background-color: #9965f4; }
        code { color: #03dac6; background-color: #2c2c2c; padding: 2px 5px; border-radius: 4px; }
    </style>
</head>
<body class="py-5">
    <div class="container">
        <h1 class="text-center mb-4">📺 IPTV Playlist Hub</h1>
        <p class="text-center text-muted">Automatically updated 24/7 from iptv-org/iptv</p>
        <div class="row">
    """
    
    categories = {"Main": [], "Categories": [], "Languages": [], "Regions": []}
    for link in m3u_links:
        rel_path = link.replace(BASE_URL, "")
        if "/" not in rel_path: categories["Main"].append(rel_path)
        elif rel_path.startswith("categories/"): categories["Categories"].append(rel_path)
        elif rel_path.startswith("languages/"): categories["Languages"].append(rel_path)
        elif rel_path.startswith("regions/"): categories["Regions"].append(rel_path)

    for cat, files in categories.items():
        if not files: continue
        html_content += f'<div class="col-12"><h2>{cat}</h2></div>'
        for f in files:
            name = f.split("/")[-1].replace(".m3u", "").capitalize()
            m3u_url = f"{USER_REPO_URL}{f}"
            html_content += f"""
            <div class="col-md-4">
                <div class="card p-3">
                    <h5>{name}</h5>
                    <p><code>{m3u_url}</code></p>
                    <a href="{m3u_url}" class="btn btn-primary btn-sm">Copy M3U Link</a>
                </div>
            </div>
            """
    
    html_content += """
        </div>
    </div>
    <script>
        document.querySelectorAll('.btn-primary').forEach(button => {
            button.onclick = (e) => {
                e.preventDefault();
                const url = button.getAttribute('href');
                navigator.clipboard.writeText(url).then(() => {
                    const originalText = button.innerText;
                    button.innerText = 'Copied!';
                    setTimeout(() => button.innerText = originalText, 2000);
                });
            }
        });
    </script>
</body>
</html>
    """
    with open("index.html", "w") as f:
        f.write(html_content)

def scrape():
    print("Starting scrape...")
    response = requests.get(SOURCE_PLAYLISTS_MD)
    if response.status_code != 200:
        print("Failed to fetch PLAYLISTS.md")
        return

    content = response.text
    m3u_links = re.findall(r'https://iptv-org\.github\.io/iptv/[\w\./-]+\.m3u', content)
    m3u_links = sorted(list(set(m3u_links)))
    
    print(f"Found {len(m3u_links)} M3U links.")
    
    # Only download first 50 for initial push to save time
    for link in m3u_links[:50]:
        relative_path = link.replace(BASE_URL, "")
        local_path = os.path.join(OUTPUT_DIR, relative_path)
        print(f"Downloading {relative_path}...")
        download_file(link, local_path)

    print("Scrape completed.")
    generate_readme(m3u_links)
    generate_index_html(m3u_links)

if __name__ == "__main__":
    scrape()
