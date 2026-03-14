#!/usr/bin/env python3
"""
Transform XML to DraCor-compliant TEI format.
This script cleans up person IDs, extracts character names, and validates structure.
Performance optimized using lxml for efficient XML processing.
"""

import re
from lxml import etree
from collections import OrderedDict
import sys
import io


def extract_character_name(full_text):
    """
    Extract clean character name from dialogue text.
    E.g., "Amal. I feel awfully well" -> "Amal"
    """
    # Split on first period or colon and take the first part
    match = re.match(r'^([^.:]+)[.:].*$', full_text.strip())
    if match:
        name = match.group(1).strip()
        # Remove stage directions in brackets
        name = re.sub(r'\[.*?\]', '', name).strip()
        return name
    return full_text.strip()


def create_clean_id(name):
    """
    Create a valid XML ID from character name.
    E.g., "Amal" -> "amal", "Royal Physician" -> "royal_physician"
    """
    # Convert to lowercase
    clean = name.lower()
    # Replace spaces and special chars with underscore
    clean = re.sub(r'[^a-z0-9]+', '_', clean)
    # Remove leading/trailing underscores
    clean = clean.strip('_')
    # Ensure it doesn't start with a number
    if clean and clean[0].isdigit():
        clean = 'char_' + clean
    return clean or 'unknown'


def get_sex_value(sex_attr):
    """Normalize sex attribute to uppercase."""
    if sex_attr:
        return sex_attr.upper()
    return "UNKNOWN"


def preprocess_invalid_xml(input_file):
    """
    Pre-process XML file to fix invalid xml:id attributes.
    Reads file as text, fixes NCName violations, returns string.
    
    Args:
        input_file: Path to input XML file
        
    Returns:
        String containing fixed XML content
    """
    print("Pre-processing XML to fix invalid IDs...")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to match xml:id attributes with invalid NCName values
    # NCName cannot contain spaces, periods, commas, quotes, and other special chars
    # except underscore, hyphen, and must not start with digit
    
    def fix_xml_id(match):
        """Fix a single xml:id attribute value."""
        full_match = match.group(0)
        attr_value = match.group(1)
        
        # Create clean ID from the invalid value
        clean_id = create_clean_id(attr_value)
        
        # Return fixed attribute
        return f'xml:id="{clean_id}"'
    
    # Match xml:id="..." where value contains invalid NCName characters
    # This will catch IDs with spaces, commas, periods, etc.
    pattern = r'xml:id="([^"]+)"'
    
    # Find all matches and fix them
    fixed_content = re.sub(pattern, fix_xml_id, content)
    
    return fixed_content


def process_xml(input_file, output_file, schema_file=None):
    """
    Process the input XML file and create DraCor-compliant output.
    
    Args:
        input_file: Path to input XML file
        output_file: Path to output XML file
        schema_file: Optional path to RelaxNG schema for validation
    """
    # Pre-process XML to fix invalid IDs
    try:
        fixed_xml_content = preprocess_invalid_xml(input_file)
    except Exception as e:
        print(f"Error during pre-processing: {e}")
        print("Attempting to parse original file...")
        fixed_xml_content = None
    
    # Parse input XML efficiently
    print(f"Parsing XML...")
    parser = etree.XMLParser(remove_blank_text=True, recover=True)
    
    try:
        if fixed_xml_content:
            # Parse from string (fixed content)
            tree = etree.parse(io.BytesIO(fixed_xml_content.encode('utf-8')), parser)
        else:
            # Parse original file
            tree = etree.parse(input_file, parser)
    except etree.XMLSyntaxError as e:
        print(f"XML Syntax Error: {e}")
        print("\nAttempting recovery mode...")
        # Try with recovery mode enabled
        parser = etree.XMLParser(remove_blank_text=True, recover=True, encoding='utf-8')
        if fixed_xml_content:
            tree = etree.parse(io.BytesIO(fixed_xml_content.encode('utf-8')), parser)
        else:
            tree = etree.parse(input_file, parser)
    
    root = tree.getroot()
    
    # Define namespaces
    ns = {'tei': 'http://www.tei-c.org/ns/1.0'}
    
    # Find all person elements
    print("Processing character list...")
    persons = root.xpath('//tei:person', namespaces=ns)
    
    # Track unique characters and their IDs
    char_map = OrderedDict()  # {old_id: (new_id, name, sex)}
    name_to_id = {}  # To handle duplicate names
    
    for person in persons:
        old_id = person.get('{http://www.w3.org/XML/1998/namespace}id', '')
        sex_attr = person.get('sex', 'UNKNOWN')
        
        # Extract persName
        persName_elem = person.find('tei:persName', namespaces=ns)
        if persName_elem is not None and persName_elem.text:
            full_text = persName_elem.text
            char_name = extract_character_name(full_text)
            
            # Create clean ID
            base_id = create_clean_id(char_name)
            
            # Handle duplicate names - use single canonical ID
            if char_name not in name_to_id:
                name_to_id[char_name] = base_id
            
            new_id = name_to_id[char_name]
            
            # Store mapping
            if old_id not in char_map:
                char_map[old_id] = (new_id, char_name, get_sex_value(sex_attr))
    
    # Remove duplicate persons and update person elements
    print(f"Found {len(char_map)} unique characters")
    listPerson = root.find('.//tei:listPerson', namespaces=ns)
    
    if listPerson is not None:
        # Clear existing persons
        listPerson.clear()
        
        # Add unique persons with clean data
        seen_ids = set()
        for old_id, (new_id, name, sex) in char_map.items():
            if new_id not in seen_ids:
                person_elem = etree.SubElement(listPerson, '{http://www.tei-c.org/ns/1.0}person')
                person_elem.set('{http://www.w3.org/XML/1998/namespace}id', new_id)
                person_elem.set('sex', sex)
                
                persName_elem = etree.SubElement(person_elem, '{http://www.tei-c.org/ns/1.0}persName')
                persName_elem.text = name
                
                seen_ids.add(new_id)
    
    # Update all 'who' attributes in sp elements and fix structure
    print("Fixing speaker elements structure...")
    sp_elements = root.xpath('//tei:sp', namespaces=ns)
    
    for sp in sp_elements:
        # Fix who attribute
        old_who = sp.get('who', '')
        if old_who.startswith('#'):
            old_id = old_who[1:]  # Remove '#'
            if old_id in char_map:
                new_id = char_map[old_id][0]
                sp.set('who', f'#{new_id}')
        
        # Fix sp structure: must have <speaker> and <p> (not just text in <speaker>)
        speaker_elem = sp.find('tei:speaker', namespaces=ns)
        if speaker_elem is not None and speaker_elem.text:
            full_text = speaker_elem.text.strip()
            
            # Extract character name and dialogue
            char_name = extract_character_name(full_text)
            
            # Split to get dialogue part
            # Pattern: "Name. Dialogue" or "Name: Dialogue"
            dialogue_match = re.match(r'^[^.:]+[.:](.*)$', full_text, re.DOTALL)
            if dialogue_match:
                dialogue = dialogue_match.group(1).strip()
                
                # Update speaker to contain only name
                speaker_elem.text = char_name
                
                # Check if <p> already exists
                p_elem = sp.find('tei:p', namespaces=ns)
                if p_elem is None and dialogue:
                    # Create <p> element for dialogue
                    p_elem = etree.Element('{http://www.tei-c.org/ns/1.0}p')
                    
                    # Handle stage directions within dialogue
                    # Pattern: text <stage>[direction]</stage> more text
                    parts = re.split(r'(\[.*?\])', dialogue)
                    
                    current_text = ""
                    for i, part in enumerate(parts):
                        if part.startswith('[') and part.endswith(']'):
                            # Add accumulated text before stage direction
                            if current_text:
                                if len(p_elem) == 0 and p_elem.text is None:
                                    p_elem.text = current_text
                                else:
                                    # Append to last element's tail
                                    if len(p_elem) > 0:
                                        if p_elem[-1].tail:
                                            p_elem[-1].tail += current_text
                                        else:
                                            p_elem[-1].tail = current_text
                                    else:
                                        p_elem.text = (p_elem.text or "") + current_text
                                current_text = ""
                            
                            # Add stage direction
                            stage_elem = etree.SubElement(p_elem, '{http://www.tei-c.org/ns/1.0}stage')
                            stage_elem.text = part[1:-1]  # Remove brackets
                        else:
                            current_text += part
                    
                    # Add any remaining text
                    if current_text:
                        if len(p_elem) == 0 and p_elem.text is None:
                            p_elem.text = current_text
                        else:
                            if len(p_elem) > 0:
                                if p_elem[-1].tail:
                                    p_elem[-1].tail += current_text
                                else:
                                    p_elem[-1].tail = current_text
                            else:
                                p_elem.text = (p_elem.text or "") + current_text
                    
                    # Add <p> after <speaker>
                    speaker_index = list(sp).index(speaker_elem)
                    sp.insert(speaker_index + 1, p_elem)
    
    # Fix bare text in div elements (wrap in <stage>)
    print("Wrapping bare text in stage directions...")
    div_elements = root.xpath('//tei:div', namespaces=ns)
    
    for div in div_elements:
        # Check for text nodes that are not wrapped
        if div.text and div.text.strip():
            text = div.text.strip()
            if text.startswith('[') and text.endswith(']'):
                # Create stage element
                stage_elem = etree.Element('{http://www.tei-c.org/ns/1.0}stage')
                stage_elem.text = text[1:-1]  # Remove brackets
                stage_elem.tail = "\n        "
                # Insert at beginning
                div.insert(0, stage_elem)
                div.text = "\n        "
        
        # Also check for tail text after child elements (e.g., after <head>)
        for child in div:
            if child.tail and child.tail.strip():
                tail_text = child.tail.strip()
                if tail_text.startswith('[') and tail_text.endswith(']'):
                    # Create stage element
                    stage_elem = etree.Element('{http://www.tei-c.org/ns/1.0}stage')
                    stage_elem.text = tail_text[1:-1]  # Remove brackets
                    # Insert after the current child
                    child_index = list(div).index(child)
                    div.insert(child_index + 1, stage_elem)
                    # Clean up the tail
                    child.tail = "\n        "
                    stage_elem.tail = "\n        "
    
    # Clean up xml:id and xml:lang on TEI root if needed
    tei_root = root
    if tei_root.get('{http://www.w3.org/XML/1998/namespace}id') == 'insert_id':
        # Generate ID from title or use default
        title_elem = root.find('.//tei:title[@type="main"]', namespaces=ns)
        if title_elem is not None and title_elem.text:
            play_id = create_clean_id(title_elem.text)
            tei_root.set('{http://www.w3.org/XML/1998/namespace}id', play_id)
        else:
            tei_root.set('{http://www.w3.org/XML/1998/namespace}id', 'play')
    
    if tei_root.get('{http://www.w3.org/XML/1998/namespace}lang') == 'insert_lang':
        tei_root.set('{http://www.w3.org/XML/1998/namespace}lang', 'eng')
    
    # Write output with pretty printing
    print(f"Writing to {output_file}...")
    tree.write(
        output_file,
        encoding='UTF-8',
        xml_declaration=True,
        pretty_print=True
    )
    
    print(f"✓ Transformation complete!")
    print(f"  - Characters: {len(seen_ids)}")
    print(f"  - Speakers updated: {len(sp_elements)}")
    
    # Validate against schema if provided
    if schema_file:
        print(f"\nValidating against {schema_file}...")
        try:
            relaxng_doc = etree.parse(schema_file)
            relaxng = etree.RelaxNG(relaxng_doc)
            
            result_tree = etree.parse(output_file)
            if relaxng.validate(result_tree):
                print("✓ Validation successful!")
            else:
                print("✗ Validation failed:")
                for error in relaxng.error_log:
                    print(f"  Line {error.line}: {error.message}")
        except Exception as e:
            print(f"Warning: Could not validate - {e}")


def main():
    """Main entry point."""
    input_file = 'input.xml'
    output_file = 'result_post_office.xml'
    schema_file = 'schema.rng'
    
    # Allow command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if len(sys.argv) > 3:
        schema_file = sys.argv[3]
    
    try:
        process_xml(input_file, output_file, schema_file)
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
