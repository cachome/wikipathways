import argparse
import glob
import io
import os
import re
import ssl
from time import sleep
import zipfile

from selenium import webdriver
# from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

import requests
from lxml import html, etree
from scour import scour

# # Enable importing local modules when directly calling as script
# if __name__ == "__main__":
#     cur_dir = os.path.join(os.path.dirname(__file__))
#     sys.path.append(cur_dir + "/..")

# from lib import download_gzip

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Organisms configured for WikiPathways caching
organisms = [
    "Homo sapiens",
    "Mus musculus"
    # "Danio rerio",
    # "Gallus gallus",
    # "Rattus norvegicus",
    # "Pan troglodytes",
    # "Canis lupus familiaris",
    # "Equus caballus",
    # "Bos taurus",
    # "Caenorhabditis elegans"
]

def get_svg_zip_url(organism):
    date = "20211110"
    base = f"https://wikipathways-data.wmcloud.org/{date}/svg/"
    org_us = organism.replace(" ", "_")
    url = f"{base}wikipathways-{date}-svg-{org_us}.zip"
    return url

def get_pathway_ids_and_names(organism):
    base_url = "https://webservice.wikipathways.org/listPathways"
    params = f"?organism={organism}&format=json"
    url = base_url + params
    response = requests.get(url)
    data = response.json()

    ids_and_names = [[pw['id'], pw['name']] for pw in data['pathways']]
    return ids_and_names

def unwrap(tree):
    ns_map = {"svg": "http://www.w3.org/2000/svg"}
    # roottree = tree.getroottree()
    normalized_class = "concat(' ', normalize-space(@class), ' ')"
    is_protein = 'contains(' + normalized_class + ', "Protein")'
    is_metabolite = 'contains(' + normalized_class + ', "Metabolite")'
    is_rna = 'contains(' + normalized_class + ', "Rna")'
    is_label = 'contains(' + normalized_class + ', "Label")'
    # rectSel = f"svg:g[{isProtein}]/svg:g[{isProtein}]/svg:rect"
    has_bloat = f"{is_protein} or {is_metabolite} or {is_rna} or {is_label}"
    rect_sel = f"//svg:g[{has_bloat}]/svg:g[{has_bloat}]/svg:rect"
    rects = tree.xpath(rect_sel, namespaces=ns_map)
    for element in rects:
        parent = element.getparent()
        grandparent = parent.getparent()
        grandparent.replace(parent, element)

    use_sel = f"//svg:g[{has_bloat}]/svg:g[{has_bloat}]/svg:use"
    uses = tree.xpath(use_sel, namespaces=ns_map)
    for element in uses:
        parent = element.getparent()
        grandparent = parent.getparent()
        grandparent.replace(parent, element)

    text_sel = f"//svg:g[{has_bloat}]/svg:g/svg:text"
    texts = tree.xpath(text_sel, namespaces=ns_map)
    for element in texts:
        parent = element.getparent()
        grandparent = parent.getparent()
        grandparent.replace(parent, element)

    return tree

def trim_markers(tree):
    """Remove unused marker elements from diagram
    """
    ns_map = {"svg": "http://www.w3.org/2000/svg"}

    used_marker_ids = []

    # Identify markers that the diagram actually uses
    elements = tree.xpath("//*")
    for element in elements:
        attrs = element.attrib
        start = attrs["marker-start"] if "marker-start" in attrs else ""
        start = start.replace("url(#", "").replace(")", "")
        end = attrs["marker-end"] if "marker-end" in attrs else ""
        end = end.replace("url(#", "").replace(")", "")
        if start not in used_marker_ids:
            used_marker_ids.append(start)
        if end not in used_marker_ids:
            used_marker_ids.append(end)

    # Remove markers that are not used
    markers = tree.xpath('//svg:g[@id="marker-defs"]/svg:marker', namespaces=ns_map)
    for marker in markers:
        attrs = marker.attrib
        id = attrs["id"] if "id" in attrs else ""
        if id not in used_marker_ids:
            marker.getparent().remove(marker)

    return tree

def custom_lossless_optimize_svg(svg, pwid):
    """Losslessly decrease size of WikiPathways SVG
    """
    svg = svg.replace('<?xml version="1.0" encoding="UTF-8"?>\n', '')
    tree = etree.fromstring(svg)
    controls = tree.xpath('//*[@class="svg-pan-zoom-control"]')[0]
    tree.remove(controls)
    metadata = tree.xpath('//*[@id="' + pwid + '-text"]')[0]
    metadata.getparent().remove(metadata)

    tree = unwrap(tree)

    tree = trim_markers(tree)

    svg = etree.tostring(tree).decode("utf-8")
    svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg

    font_family = "\'Liberation Sans\', Arial, sans-serif"
    svg = re.sub('font-family="Arial"', '', svg)
    svg = re.sub(f'font-family="{font_family}"', '', svg)
    style = (
        "<style>" +
            "svg {" +
            f"font-family: {font_family}; "
            "}" +
            # "path {fill: transparent;}" +
            "text {" +
                "dominant-baseline: central;" +
                "overflow: hidden;" +
            #   "stroke: #000; " +
            #   "fill: #000;" +
            "}" +
            # "g > a {" +
            #   "color: #000;" +
            # "}" +
        "</style>"
    )
    old_style = '<style type="text/css">'
    svg = re.sub(old_style, style + old_style, svg)

    svg = re.sub('xml:space="preserve"', '', svg)

    # Condense colors.
    # Consider using an abstract, general approach instead of hard-coding.
    svg = re.sub('#000000', '#000', svg)
    svg = re.sub('#ff0000', '#f00', svg)
    svg = re.sub('#00ff00', '#0f0', svg)
    svg = re.sub('#0000ff', '#00f', svg)
    svg = re.sub('#00ffff', '#0ff', svg)
    svg = re.sub('#ff00ff', '#f0f', svg)
    svg = re.sub('#ffff00', '#ff0', svg)
    svg = re.sub('#ffffff', '#fff', svg)
    svg = re.sub('#cc0000', '#c00', svg)
    svg = re.sub('#00cc00', '#0c0', svg)
    svg = re.sub('#0000cc', '#00c', svg)
    svg = re.sub('#00cccc', '#0cc', svg)
    svg = re.sub('#cc00cc', '#c0c', svg)
    svg = re.sub('#cccc00', '#cc0', svg)
    svg = re.sub('#cccccc', '#ccc', svg)
    svg = re.sub('#999999', '#999', svg)
    svg = re.sub('#808080', 'grey', svg)

    # Remove "px" from attributes where numbers are assumed to be pixels.
    svg = re.sub(r'width="([0-9.]+)px"', r'width="\1"', svg)
    svg = re.sub(r'height="([0-9.]+)px"', r'height="\1"', svg)
    svg = re.sub(r'stroke-width="([0-9.]+)px"', r'stroke-width="\1"', svg)

    svg = re.sub('fill="inherit"', '', svg)
    svg = re.sub('stroke-width="inherit"', '', svg)
    svg = re.sub('color="inherit"', '', svg)

    svg = re.sub('fill-opacity="0"', '', svg)
    svg = re.sub('dominant-baseline="central"', '', svg)
    svg = re.sub('overflow="hidden"', '', svg)

    # # Match any anchor or group tag, up until closing angle bracket (>), that
    # # includes a color attribute with the value black (#000).
    # # For such matches, remove the color attribute but not anything else.
    # svg = re.sub(r'<a([^>]*)(color="#000")', r'<a \1', svg)
    svg = re.sub(r'<g([^>]*)(color="#000")', r'<g \1', svg)

    svg = re.sub(r'<(rect class="Icon"[^>]*)(color="#000")', r'<rect \1', svg)
    svg = re.sub(r'<(rect class="Icon"[^>]*)(fill="#000")', r'<rect \1', svg)

    svg = re.sub(r'<(text class="Text"[^>]*)(fill="#000")', r'<\1', svg)
    svg = re.sub(r'<(text class="Text"[^>]*)(stroke="white" stroke-width="0")', r'<\1', svg)

    svg = re.sub(r'<(text[^>]*)(clip\-path="[^"]*)"', r'<\1', svg)
    # svg = re.sub(r'<defs><clipPath.*</defs>', r'', svg)

    svg = re.sub(r'class="([^"]*)( Node)"', r'class="\1"', svg)
    svg = re.sub(r'class="([^"]*)( textContent)"', r'class="\1"', svg)

    svg = re.sub(r'id="[^"]*-text-clipPath"', '', svg)

    # Remove class attributes from elements where it can be deduced
    svg = re.sub(r'<rect([^>]*)(class="[^"]*)"', r'<rect \1', svg)
    svg = re.sub(r'<text([^>]*)(class="[^"]*)"', r'<text \1', svg)
    svg = re.sub(r'<tspan([^>]*)(class="[^"]*)"', r'<tspan \1', svg)

    svg = re.sub(r'<path([^>]*)(id="[^"]*)"', r'<path \1', svg)
    # svg = re.sub(r'<path([^>]*)(fill="transparent")', r'<path \1', svg)

    # svg = re.sub('text-anchor="middle"', '', svg)

    svg = re.sub(pwid.lower(), '', svg)

    svg = re.sub(r'markerendarrow', 'mea', svg)
    svg = re.sub(r'markerendmim', 'mem', svg)
    svg = re.sub('mea000000white', 'mea', svg)
    svg = re.sub(r'mea([^white]+)white', r'mea\1', svg)
    svg = re.sub('mea000000', 'mea000', svg)
    svg = re.sub('meaff0000', 'meaf00', svg)
    svg = re.sub('mea00ff00', 'mea0f0', svg)
    svg = re.sub('mea0000ff', 'mea00f', svg)
    svg = re.sub('mea00ffff', 'mea0ff', svg)
    svg = re.sub('meaff00ff', 'meaf0f', svg)
    svg = re.sub('meaffff00', 'meaff0', svg)
    svg = re.sub('meaffffff', 'meafff', svg)
    svg = re.sub('meacc0000', 'meac00', svg)
    svg = re.sub('mea00cc00', 'mea0c0', svg)
    svg = re.sub('mea0000cc', 'mea00c', svg)
    svg = re.sub('mea00cccc', 'mea0cc', svg)
    svg = re.sub('meacc00cc', 'meac0c', svg)
    svg = re.sub('meacccc00', 'meacc0', svg)
    svg = re.sub('meacccccc', 'meaccc', svg)
    svg = re.sub('mea999999', 'mea999', svg)
    svg = re.sub('mea808080', 'meagrey', svg)
    svg = re.sub('000000white', '000', svg)

    svg = re.sub(r'id="[^"]*-icon" ', '', svg)
    svg = re.sub(r'id="[^"]*-text" class="[^"]*"', '', svg)

    svg = re.sub(r'\d*\.\d{2,}', lambda m: format(float(m.group(0)), '.2f'), svg)

    svg = re.sub(
        r'text-anchor="middle"><tspan\s+x="0" y="0"',
        r'text-anchor="middle"><tspan ',
        svg
    )

    return svg

def custom_lossy_optimize_svg(svg):
    """Lossily decrease size of WikiPathways SVG

    The broad principle is to remove data that does not affect static render,
    but could affect dynamic rendering (e.g. highlighting a specific gene).

    Data removed here could be inferred and/or repopulated in the DOM given a
    schema.  Such a schema would first need to be defined and made available in
    client-side software.  It might make sense to do that in the pvjs library.
    """

    # Remove non-leaf pathway categories.
    svg = re.sub('SingleFreeNode DataNode ', '', svg)
    svg = re.sub('DataNode SingleFreeNode ', '', svg)
    svg = re.sub('Shape SingleFreeNode', '', svg)
    svg = re.sub('SingleFreeNode Label', 'Label', svg)
    svg = re.sub('Label SingleFreeNode', 'Label', svg)
    svg = re.sub('Edge Interaction ', '', svg)
    svg = re.sub('Interaction Edge ', '', svg)
    svg = re.sub('Edge Interaction', 'Edge', svg)
    svg = re.sub('Interaction Edge', 'Edge', svg)
    # svg = re.sub('class="Interaction,Edge" ', '', svg)
    svg = re.sub('GraphicalLine Edge', 'Edge', svg)
    svg = re.sub('Metabolite Node Icon', 'Icon', svg)
    svg = re.sub('Label Node Icon', 'Icon', svg)
    svg = re.sub('GroupGroup Node Icon', 'Icon', svg)
    svg = re.sub('GroupComplex Node Icon', 'Icon', svg)
    svg = re.sub('Group Complex Icon', 'Icon', svg)

    svg = re.sub('Anchor Burr', 'AB', svg)


    svg = re.sub(r'class="[^"]*,[^"]*"', '', svg)

    # Interaction data attributes
    svg = re.sub('SBO_[0-9]+\s*', '', svg)

    # Gene data attributes
    svg = re.sub('Entrez_Gene_[0-9]+\s*', '', svg)
    svg = re.sub('Ensembl_ENS\w+\s*', '', svg)
    svg = re.sub('HGNC_\w+\s*', '', svg)
    svg = re.sub('Wikidata_Q[0-9]+\s*', '', svg)
    svg = re.sub('P594_ENSG[0-9]+\s*', '', svg)
    svg = re.sub('P351_\w+\s*', '', svg)
    svg = re.sub('P353_\w+\s*', '', svg)
    svg = re.sub('P594_ENSG[0-9]+\s*', '', svg)

    # Metabolite data attributes
    svg = re.sub('P683_CHEBI_[0-9]+\s*', '', svg)
    svg = re.sub('P2057_\w+\s*', '', svg)
    svg = re.sub('ChEBI_[0-9]+\s*', '', svg)
    svg = re.sub('ChEBI_CHEBI[0-9]+\s*', '', svg)
    svg = re.sub('ChEBI_CHEBI_[0-9]+\s*', '', svg)
    svg = re.sub('P683_[0-9]+', '', svg)
    svg = re.sub('HMDB_\w+\s*', '', svg)
    svg = re.sub(' Enzyme_Nomenclature_[0-9_]*', '', svg)
    svg = re.sub(' PubChem-compound_[0-9]*', '', svg)
    svg = re.sub(' Chemspider_[0-9]*', '', svg)
    svg = re.sub(' CAS_[0-9-]+', '', svg)

    # Other miscellaneous data attributes
    svg = re.sub(' Pfam_PF[0-9]+', '', svg)
    svg = re.sub(' Uniprot-TrEMBL_\w+', '', svg)
    svg = re.sub(' WikiPathways_WP[0-9]+', '', svg)

    # Group data attributes
    svg = re.sub('Group GroupGroup', 'GroupGroup', svg)
    svg = re.sub('Group GroupNone', 'GroupNone', svg)
    svg = re.sub('Group Complex GroupComplex', 'GroupComplex', svg)

    svg = re.sub('about="[^"]*"', '', svg)
    svg = re.sub('typeof="[^"]*"', '', svg)

    svg = re.sub(r'xlink:href="http[^\'" >]*"', '', svg)

    svg = re.sub(r' href="#none"', '', svg)
    svg = re.sub('target="_blank"', '', svg)

    svg = re.sub('font-weight="bold"', '', svg)

    return svg


class WikiPathwaysCache():

    def __init__(self, output_dir="data/", reuse=False):
        self.output_dir = output_dir
        self.tmp_dir = f"tmp/"
        self.reuse = reuse
        # self.driver = webdriver.Chrome(ChromeDriverManager().install())
        # self.driver.implicitly_wait(3) # seconds

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        if not os.path.exists(self.tmp_dir):
            os.makedirs(self.tmp_dir)

    def fetch_svgs(self, ids_and_names, org_dir):

        prev_error_wpids = []
        error_wpids = []

        error_path = org_dir + "error_wpids.csv"
        if os.path.exists(error_path):
            with open(error_path) as f:
                prev_error_wpids = f.read().split(",")
                error_wpids = prev_error_wpids

        for i_n in ids_and_names:
            id = i_n[0]
            svg_path = org_dir + id + ".svg"

            if self.reuse:
                if os.path.exists(svg_path):
                    print(f"Found cache; skip processing {id}")
                    continue
                elif id in prev_error_wpids:
                    print(f"Found previous error; skip processing {id}")
                    continue

            # url = f"https://pathway-viewer.toolforge.org/?id={id}"

            # url = f"https://www.wikipathways.org/wpi/PathwayWidget.php?id={id}"
            url = f"https://www.wikipathways.org/index.php/Pathway:{id}?view=widget"
            # url = f"https://example.com"
            self.driver.get(url)

            try:
                sleep(1)
                selector = "svg.Diagram"
                raw_content = self.driver.find_element_by_css_selector(selector)
                content = raw_content.get_attribute("outerHTML")
            except Exception as e:
                print(f"Encountered error when stringifying SVG for {id}")
                error_wpids.append(id)
                with open(error_path, "w") as f:
                    f.write(",".join(error_wpids))
                sleep(0.5)
                continue

            svg = content.replace(
                'typeof="Diagram" xmlns:xlink="http://www.w3.org/1999/xlink"',
                'typeof="Diagram"'
            )

            print("Preparing and writing " + svg_path)

            svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg

            with open(svg_path, "w") as f:
                f.write(svg)
            sleep(1)

    def optimize_svgs(self, org_dir):
        for svg_path in glob.glob(f'{org_dir}*.svg'):
        # for svg_path in ["tmp/homo-sapiens/WP231.svg"]: # debug
            with open(svg_path, 'r') as f:
                svg = f.read()

            svg = re.sub("fill-opacity:inherit;", "", svg)
            # print('clean_svg')
            # print(clean_svg)
            original_name = svg_path.split("/")[-1]
            name = original_name.split(".svg")[0]
            pwid = re.search(r"WP\d+", name).group() # pathway ID
            optimized_svg_path = self.output_dir + pwid + ".svg"
            print(f"Optimizing to create: {optimized_svg_path}")

            scour_options = scour.sanitizeOptions()
            scour_options.remove_metadata = False
            scour_options.newlines = False
            scour_options.strip_comments = True
            scour_options.strip_ids = False
            scour_options.shorten_ids = False
            scour_options.strip_xml_space_attribute = True
            scour_options.keep_defs = True

            try:
                clean_svg = scour.scourString(svg, options=scour_options)
            except Exception as e:
                print(f"Encountered error while optimizing SVG for {pwid}")
                continue

            repo_url = "https://github.com/eweitz/cachome/tree/main/"
            code_url = f"{repo_url}src/wikipathways.py"
            data_url = f"{repo_url}{optimized_svg_path}"
            wp_url = f"https://www.wikipathways.org/index.php/Pathway:{pwid}"
            provenance = "\n".join([
                "<!--",
                f"  WikiPathways page: {wp_url}",
                f"  URL for this compressed file: {data_url}",
                # f"  Uncompressed SVG file: {original_name}",
                # f"  From upstream ZIP archive: {url}",
                f"  Source code for compression: {code_url}",
                "-->"
            ])

            clean_svg = clean_svg.replace(
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<?xml version="1.0" encoding="UTF-8"?>\n' + provenance
            )



            # clean_svg = re.sub('tspan x="0" y="0"', 'tspan', clean_svg)
            clean_svg = custom_lossless_optimize_svg(clean_svg, pwid)
            clean_svg = custom_lossy_optimize_svg(clean_svg)

            with open(optimized_svg_path, "w") as f:
                f.write(clean_svg)


    def populate_by_org(self, organism):
        """Fill caches for a configured organism
        """
        org_dir = self.tmp_dir + organism.lower().replace(" ", "-") + "/"
        if not os.path.exists(org_dir):
            os.makedirs(org_dir)

        # ids_and_names = get_pathway_ids_and_names(organism)
        ids_and_names = [["WP231", "test"]]
        # print("ids_and_names", ids_and_names)
        self.fetch_svgs(ids_and_names, org_dir)
        self.optimize_svgs(org_dir)

    def populate(self):
        """Fill caches for all configured organisms

        Consider parallelizing this.
        """
        for organism in organisms:
            self.populate_by_org(organism)

# Command-line handler
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Directory to put outcome data.  (default: %(default))"
        ),
        default="data/"
    )
    parser.add_argument(
        "--reuse",
        help=(
            "Whether to use previously-downloaded raw SVG zip archives"
        ),
        action="store_true"
    )
    args = parser.parse_args()
    output_dir = args.output_dir
    reuse = args.reuse

    WikiPathwaysCache(output_dir, reuse).populate()
