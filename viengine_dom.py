from html import escape
from html.parser import HTMLParser
import re

from viengine_js import EventTarget, JavaScriptError


VOID_ELEMENTS = {
	"area", "base", "br", "col", "embed", "hr", "img", "input",
	"link", "meta", "param", "source", "track", "wbr",
}


class NodeList:
	def __init__(self, nodes=()):
		self._nodes = list(nodes)

	@property
	def length(self):
		return len(self._nodes)

	def item(self, index):
		try:
			return self._nodes[int(index)]
		except (ValueError, IndexError):
			return None

	def forEach(self, callback):
		for index, node in enumerate(self._nodes):
			callback(node, index, self)

	def __iter__(self):
		return iter(self._nodes)

	def __len__(self):
		return len(self._nodes)

	def __getitem__(self, index):
		return self._nodes[index]


class Node(EventTarget):
	ELEMENT_NODE = 1
	TEXT_NODE = 3
	COMMENT_NODE = 8
	DOCUMENT_NODE = 9
	DOCUMENT_FRAGMENT_NODE = 11

	def __init__(self, node_type, node_name):
		super().__init__()
		self.nodeType = node_type
		self.nodeName = node_name
		self.parentNode = None
		self.childNodes = NodeList()

	@property
	def children(self):
		return NodeList(child for child in self.childNodes if child.nodeType == Node.ELEMENT_NODE)

	@property
	def firstChild(self):
		return self.childNodes[0] if self.childNodes else None

	@property
	def lastChild(self):
		return self.childNodes[-1] if self.childNodes else None

	@property
	def parentElement(self):
		return self.parentNode if getattr(self.parentNode, "nodeType", None) == Node.ELEMENT_NODE else None

	@property
	def nextSibling(self):
		return self._sibling(1)

	@property
	def previousSibling(self):
		return self._sibling(-1)

	def _sibling(self, direction):
		if self.parentNode is None:
			return None
		nodes = self.parentNode.childNodes._nodes
		try:
			return nodes[nodes.index(self) + direction]
		except (ValueError, IndexError):
			return None

	@property
	def textContent(self):
		if self.nodeType in (Node.TEXT_NODE, Node.COMMENT_NODE):
			return self.data
		return "".join(child.textContent for child in self.childNodes)

	@textContent.setter
	def textContent(self, value):
		if self.nodeType in (Node.TEXT_NODE, Node.COMMENT_NODE):
			self.data = str(value or "")
			return
		self.replaceChildren(TextNode(str(value or "")) if value else None)

	def appendChild(self, child):
		if not isinstance(child, Node):
			raise JavaScriptError("appendChild expects a Node")
		if child is self or child.contains(self):
			raise JavaScriptError("Cannot insert a node into itself")
		if child.nodeType == Node.DOCUMENT_FRAGMENT_NODE:
			for fragment_child in list(child.childNodes):
				self.appendChild(fragment_child)
			return child
		if child.parentNode is not None:
			child.parentNode.removeChild(child)
		child.parentNode = self
		self.childNodes._nodes.append(child)
		return child

	def insertBefore(self, child, reference):
		if reference is None:
			return self.appendChild(child)
		if reference.parentNode is not self:
			raise JavaScriptError("Reference node is not a child")
		if child.parentNode is not None:
			child.parentNode.removeChild(child)
		index = self.childNodes._nodes.index(reference)
		child.parentNode = self
		self.childNodes._nodes.insert(index, child)
		return child

	def removeChild(self, child):
		self.childNodes._nodes.remove(child)
		child.parentNode = None
		return child

	def replaceChild(self, new_child, old_child):
		self.insertBefore(new_child, old_child)
		self.removeChild(old_child)
		return old_child

	def replaceChildren(self, *children):
		for child in list(self.childNodes):
			self.removeChild(child)
		for child in children:
			if child is None:
				continue
			self.appendChild(child if isinstance(child, Node) else TextNode(str(child)))

	def contains(self, other):
		node = other
		while node is not None:
			if node is self:
				return True
			node = node.parentNode
		return False

	def remove(self):
		if self.parentNode is not None:
			self.parentNode.removeChild(self)

	def cloneNode(self, deep=False):
		if self.nodeType == Node.TEXT_NODE:
			clone = TextNode(self.data)
		elif self.nodeType == Node.COMMENT_NODE:
			clone = Comment(self.data)
		elif isinstance(self, Element):
			clone = Element(self.localName, self.attributes)
		else:
			clone = DocumentFragment()
		if deep:
			for child in self.childNodes:
				clone.appendChild(child.cloneNode(True))
		return clone

	@property
	def innerHTML(self):
		return "".join(serialize_node(child) for child in self.childNodes)

	@innerHTML.setter
	def innerHTML(self, markup):
		fragment = parse_fragment(str(markup or ""))
		self.replaceChildren(*list(fragment.childNodes))

	def getElementsByTagName(self, name):
		return NodeList(node for node in descendants(self) if node.nodeType == Node.ELEMENT_NODE and (name == "*" or node.localName == str(name).lower()))

	def querySelector(self, selector):
		nodes = self.querySelectorAll(selector)
		return nodes[0] if nodes else None

	def querySelectorAll(self, selector):
		return query_selector_all(self, selector)

	def dispatchEvent(self, event):
		target = event.target if getattr(event, "target", None) is not None else self
		result = super().dispatchEvent(event)
		if getattr(event, "bubbles", False) and not getattr(event, "propagationStopped", False):
			parent = self.parentNode
			while parent is not None:
				event.currentTarget = parent
				EventTarget.dispatchEvent(parent, event)
				event.target = target
				if getattr(event, "propagationStopped", False):
					break
				parent = parent.parentNode
		return result


class TextNode(Node):
	def __init__(self, data):
		super().__init__(Node.TEXT_NODE, "#text")
		self.data = str(data)

	@property
	def nodeValue(self):
		return self.data

	@nodeValue.setter
	def nodeValue(self, value):
		self.data = str(value or "")


class Comment(Node):
	def __init__(self, data):
		super().__init__(Node.COMMENT_NODE, "#comment")
		self.data = str(data)


class DOMTokenList:
	def __init__(self, element):
		self.element = element

	def _tokens(self):
		return (self.element.getAttribute("class") or "").split()

	def _save(self, tokens):
		self.element.setAttribute("class", " ".join(dict.fromkeys(tokens)))

	@property
	def value(self):
		return " ".join(self._tokens())

	@value.setter
	def value(self, value):
		self.element.setAttribute("class", value)

	@property
	def length(self):
		return len(self._tokens())

	def contains(self, token):
		return str(token) in self._tokens()

	def add(self, *tokens):
		current = self._tokens()
		current.extend(str(token) for token in tokens if str(token) not in current)
		self._save(current)

	def remove(self, *tokens):
		removed = {str(token) for token in tokens}
		self._save([token for token in self._tokens() if token not in removed])

	def toggle(self, token, force=None):
		token = str(token)
		present = self.contains(token)
		should_add = not present if force is None else bool(force)
		if should_add and not present:
			self.add(token)
		elif not should_add and present:
			self.remove(token)
		return should_add

	def item(self, index):
		tokens = self._tokens()
		return tokens[int(index)] if 0 <= int(index) < len(tokens) else None

	def __contains__(self, token):
		return self.contains(token)

	def __iter__(self):
		return iter(self._tokens())


class StyleDeclaration:
	def __init__(self, element):
		object.__setattr__(self, "_element", element)

	def _properties(self):
		result = {}
		for declaration in (self._element.getAttribute("style") or "").split(";"):
			if ":" in declaration:
				key, value = declaration.split(":", 1)
				result[key.strip().lower()] = value.strip()
		return result

	def _store(self, properties):
		self._element.setAttribute("style", "; ".join(f"{key}: {value}" for key, value in properties.items()))

	@property
	def cssText(self):
		return self._element.getAttribute("style")

	@cssText.setter
	def cssText(self, value):
		self._element.setAttribute("style", value)

	def getPropertyValue(self, name):
		return self._properties().get(str(name).lower(), "")

	def setProperty(self, name, value, priority=""):
		properties = self._properties()
		value = str(value)
		if priority:
			value += " !" + str(priority).lstrip("!")
		properties[str(name).lower()] = value
		self._store(properties)

	def removeProperty(self, name):
		properties = self._properties()
		result = properties.pop(str(name).lower(), "")
		self._store(properties)
		return result

	def __getattr__(self, name):
		css_name = re.sub(r"[A-Z]", lambda match: "-" + match.group(0).lower(), name)
		return self.getPropertyValue(css_name)

	def __setattr__(self, name, value):
		if name == "_element":
			object.__setattr__(self, name, value)
		else:
			css_name = re.sub(r"[A-Z]", lambda match: "-" + match.group(0).lower(), name)
			self.setProperty(css_name, value)


class Element(Node):
	def __init__(self, tag_name, attributes=None):
		self.localName = str(tag_name).lower()
		super().__init__(Node.ELEMENT_NODE, self.localName.upper())
		self.attributes = {str(key).lower(): str(value or "") for key, value in (attributes or {}).items()}
		self._class_list = DOMTokenList(self)
		self._style = StyleDeclaration(self)
		self._canvas_surface = None
		if self.localName == "canvas":
			width = int(self.attributes.get("width", 300) or 300)
			height = int(self.attributes.get("height", 150) or 150)
			self._canvas_surface = CanvasSurface(width, height)

	@property
	def tagName(self):
		return self.nodeName

	@property
	def id(self):
		return self.getAttribute("id")

	@id.setter
	def id(self, value):
		self.setAttribute("id", value)

	@property
	def className(self):
		return self.getAttribute("class")

	@className.setter
	def className(self, value):
		self.setAttribute("class", value)

	@property
	def classList(self):
		return self._class_list

	@property
	def style(self):
		return self._style

	@property
	def innerText(self):
		return self.textContent

	@innerText.setter
	def innerText(self, value):
		self.textContent = value

	@property
	def outerHTML(self):
		return serialize_node(self)

	@property
	def value(self):
		return self.getAttribute("value")

	@value.setter
	def value(self, value):
		self.setAttribute("value", value)

	@property
	def width(self):
		return self._canvas_surface.width if self._canvas_surface else int(self.getAttribute("width") or 0)

	@width.setter
	def width(self, value):
		if self._canvas_surface:
			self._canvas_surface.width = value
		self.setAttribute("width", value)

	@property
	def height(self):
		return self._canvas_surface.height if self._canvas_surface else int(self.getAttribute("height") or 0)

	@height.setter
	def height(self, value):
		if self._canvas_surface:
			self._canvas_surface.height = value
		self.setAttribute("height", value)

	def getContext(self, context_type, options=None):
		if self._canvas_surface is None:
			return None
		return self._canvas_surface.getContext(context_type, options)

	def toDataURL(self, mime_type="image/png"):
		if self._canvas_surface is None:
			return "data:,"
		return self._canvas_surface.toDataURL(mime_type)

	def getAttribute(self, name):
		return self.attributes.get(str(name).lower())

	def setAttribute(self, name, value):
		self.attributes[str(name).lower()] = str(value)

	def hasAttribute(self, name):
		return str(name).lower() in self.attributes

	def removeAttribute(self, name):
		self.attributes.pop(str(name).lower(), None)

	def toggleAttribute(self, name, force=None):
		present = self.hasAttribute(name)
		should_have = not present if force is None else bool(force)
		if should_have:
			self.setAttribute(name, "")
		else:
			self.removeAttribute(name)
		return should_have

	def matches(self, selector):
		return matches_selector(self, selector)

	def closest(self, selector):
		node = self
		while node is not None and node.nodeType == Node.ELEMENT_NODE:
			if node.matches(selector):
				return node
			node = node.parentElement
		return None

	def insertAdjacentHTML(self, position, markup):
		fragment = parse_fragment(markup)
		nodes = list(fragment.childNodes)
		position = str(position).lower()
		if position == "beforebegin" and self.parentNode:
			for node in nodes:
				self.parentNode.insertBefore(node, self)
		elif position == "afterend" and self.parentNode:
			reference = self.nextSibling
			for node in nodes:
				self.parentNode.insertBefore(node, reference)
		elif position == "afterbegin":
			for node in reversed(nodes):
				self.insertBefore(node, self.firstChild)
		elif position == "beforeend":
			for node in nodes:
				self.appendChild(node)
		else:
			raise JavaScriptError("Invalid insertAdjacentHTML position")

	def getBoundingClientRect(self):
		return {"x": 0, "y": 0, "top": 0, "right": 0, "bottom": 0, "left": 0, "width": 0, "height": 0}

	def click(self):
		from viengine_js import JSEvent

		self.dispatchEvent(JSEvent("click", {"bubbles": True, "cancelable": True}))


class DocumentFragment(Node):
	def __init__(self):
		super().__init__(Node.DOCUMENT_FRAGMENT_NODE, "#document-fragment")


class Document(Node):
	def __init__(self):
		super().__init__(Node.DOCUMENT_NODE, "#document")
		self.documentElement = None
		self.head = None
		self.body = None
		self.defaultView = None
		self.readyState = "loading"
		self.URL = ""
		self._doctype = ""

	@property
	def title(self):
		title = self.querySelector("title")
		return title.textContent if title else ""

	@title.setter
	def title(self, value):
		if self.head is None:
			return
		title = self.head.querySelector("title")
		if title is None:
			title = self.createElement("title")
			self.head.appendChild(title)
		title.textContent = value

	def createElement(self, tag_name):
		return Element(tag_name)

	def createTextNode(self, data):
		return TextNode(data)

	def createDocumentFragment(self):
		return DocumentFragment()

	def getElementById(self, element_id):
		element_id = str(element_id)
		return next((node for node in descendants(self) if node.nodeType == Node.ELEMENT_NODE and node.id == element_id), None)

	def getElementsByName(self, name):
		name = str(name)
		return NodeList(node for node in descendants(self) if node.nodeType == Node.ELEMENT_NODE and node.getAttribute("name") == name)

	def write(self, *parts):
		if self.body is None:
			self._ensure_structure()
		fragment = parse_fragment("".join(map(str, parts)))
		for child in list(fragment.childNodes):
			self.body.appendChild(child)

	def writeln(self, *parts):
		self.write(*parts, "\n")

	def open(self):
		self.replaceChildren()
		self.documentElement = self.head = self.body = None
		self._ensure_structure()
		return self

	def close(self):
		self.readyState = "complete"

	def _ensure_structure(self):
		if self.documentElement is None:
			root = Element("html")
			head = Element("head")
			body = Element("body")
			root.appendChild(head)
			root.appendChild(body)
			self.appendChild(root)
			self.documentElement, self.head, self.body = root, head, body
			return
		if self.head is None:
			self.head = Element("head")
			self.documentElement.insertBefore(self.head, self.documentElement.firstChild)
		if self.body is None:
			self.body = Element("body")
			self.documentElement.appendChild(self.body)

	def to_html(self):
		return self._doctype + "".join(serialize_node(child) for child in self.childNodes)


class _TreeBuilder(HTMLParser):
	def __init__(self, document, root, fragment=False):
		super().__init__(convert_charrefs=True)
		self.document = document
		self.fragment = fragment
		self.stack = [root]

	def handle_starttag(self, tag, attrs):
		tag = tag.lower()
		attr_dict = {name: value or "" for name, value in attrs}
		if not self.fragment and tag == "html" and self.document.documentElement is None:
			element = Element(tag, attr_dict)
			self.document.documentElement = element
		elif not self.fragment and tag == "head" and self.document.head is None:
			element = Element(tag, attr_dict)
			self.document.head = element
		elif not self.fragment and tag == "body" and self.document.body is None:
			element = Element(tag, attr_dict)
			self.document.body = element
		else:
			element = Element(tag, attr_dict)
		self.stack[-1].appendChild(element)
		if tag not in VOID_ELEMENTS:
			self.stack.append(element)

	def handle_startendtag(self, tag, attrs):
		self.handle_starttag(tag, attrs)
		if tag.lower() not in VOID_ELEMENTS:
			self.handle_endtag(tag)

	def handle_endtag(self, tag):
		tag = tag.lower()
		for index in range(len(self.stack) - 1, 0, -1):
			if getattr(self.stack[index], "localName", "") == tag:
				del self.stack[index:]
				return

	def handle_data(self, data):
		if data:
			self.stack[-1].appendChild(TextNode(data))

	def handle_comment(self, data):
		self.stack[-1].appendChild(Comment(data))

	def handle_decl(self, decl):
		if not self.fragment and decl.lower().startswith("doctype"):
			self.document._doctype = "<!" + decl + ">"


def parse_fragment(markup):
	fragment = DocumentFragment()
	_TreeBuilder(Document(), fragment, fragment=True).feed(str(markup or ""))
	return fragment


def parse_html(markup, url=""):
	document = Document()
	document.URL = str(url)
	_TreeBuilder(document, document).feed(str(markup or ""))
	if document.documentElement is None:
		loose_nodes = list(document.childNodes)
		document.replaceChildren()
		document._ensure_structure()
		for child in loose_nodes:
			document.body.appendChild(child)
	else:
		document._ensure_structure()
	document.readyState = "complete"
	return document


def descendants(node):
	for child in node.childNodes:
		yield child
		yield from descendants(child)


def _split_selector(selector):
	return [part for part in re.split(r"\s*\>\s*|\s+", selector.strip()) if part]


def _matches_compound(element, selector):
	if selector == "*":
		return True
	tag_match = re.match(r"^([a-zA-Z][\w-]*|\*)", selector)
	if tag_match and tag_match.group(1) != "*" and element.localName != tag_match.group(1).lower():
		return False
	for element_id in re.findall(r"#([\w-]+)", selector):
		if element.id != element_id:
			return False
	for class_name in re.findall(r"\.([\w-]+)", selector):
		if not element.classList.contains(class_name):
			return False
	for attribute_match in re.finditer(r"\[\s*([\w-]+)(?:\s*=\s*(['\"]?)(.*?)\2)?\s*\]", selector):
		name, _, expected = attribute_match.groups()
		if not element.hasAttribute(name):
			return False
		if expected is not None and element.getAttribute(name) != expected:
			return False
	return True


def matches_selector(element, selector):
	for group in str(selector).split(","):
		parts = _split_selector(group)
		if not parts or not _matches_compound(element, parts[-1]):
			continue
		ancestor = element.parentElement
		matched = True
		for part in reversed(parts[:-1]):
			while ancestor is not None and not _matches_compound(ancestor, part):
				ancestor = ancestor.parentElement
			if ancestor is None:
				matched = False
				break
			ancestor = ancestor.parentElement
		if matched:
			return True
	return False


def query_selector_all(root, selector):
	return NodeList(
		node for node in descendants(root)
		if node.nodeType == Node.ELEMENT_NODE and matches_selector(node, selector)
	)


def serialize_node(node):
	if node.nodeType == Node.TEXT_NODE:
		if node.parentElement and node.parentElement.localName in ("script", "style"):
			return node.data
		return escape(node.data, quote=False)
	if node.nodeType == Node.COMMENT_NODE:
		return "<!--" + node.data + "-->"
	if node.nodeType in (Node.DOCUMENT_NODE, Node.DOCUMENT_FRAGMENT_NODE):
		return "".join(serialize_node(child) for child in node.childNodes)
	attributes = "".join(
		f' {name}="{escape(value, quote=True)}"'
		for name, value in node.attributes.items()
	)
	opening = "<" + node.localName + attributes + ">"
	if node.localName in VOID_ELEMENTS:
		return opening
	return opening + "".join(serialize_node(child) for child in node.childNodes) + "</" + node.localName + ">"
