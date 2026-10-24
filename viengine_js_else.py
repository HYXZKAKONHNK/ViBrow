import heapq
import itertools # интерполс блять
import math
import re
import struct
import base64
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class JavaScriptError(Exception):
	pass


class _Undefined:
	def __repr__(self):
		return "undefined"


UNDEFINED = _Undefined()


class ArrayBuffer:
	def __init__(self, byte_length):
		if isinstance(byte_length, ArrayBuffer):
			byte_length = byte_length.byteLength
		length = int(byte_length)
		if length < 0:
			raise JavaScriptError("ArrayBuffer length must not be negative")
		self._data = bytearray(length)

	@property
	def byteLength(self):
		return len(self._data)

	def slice(self, start=0, end=None):
		start = _normalize_index(start, self.byteLength)
		end = self.byteLength if end is None else _normalize_index(end, self.byteLength)
		buffer = ArrayBuffer(max(0, end - start))
		buffer._data[:] = self._data[start:end]
		return buffer

	@staticmethod
	def isView(value):
		return isinstance(value, (DataView, TypedArray))


class DataView:
	_FORMATS = {
		"Int8": ("b", 1), "Uint8": ("B", 1),
		"Int16": ("h", 2), "Uint16": ("H", 2),
		"Int32": ("i", 4), "Uint32": ("I", 4),
		"Float32": ("f", 4), "Float64": ("d", 8),
	}

	def __init__(self, buffer, byte_offset=0, byte_length=None):
		if not isinstance(buffer, ArrayBuffer):
			raise JavaScriptError("DataView expects an ArrayBuffer")
		self.buffer = buffer
		self.byteOffset = int(byte_offset)
		self.byteLength = buffer.byteLength - self.byteOffset if byte_length is None else int(byte_length)
		if self.byteOffset < 0 or self.byteLength < 0 or self.byteOffset + self.byteLength > buffer.byteLength:
			raise JavaScriptError("DataView range is outside the buffer")

	def _get(self, kind, offset, little_endian=False):
		format_code, size = self._FORMATS[kind]
		position = self.byteOffset + int(offset)
		if offset < 0 or position + size > self.byteOffset + self.byteLength:
			raise JavaScriptError("DataView access is outside the view")
		order = "<" if little_endian else ">"
		return struct.unpack_from(order + format_code, self.buffer._data, position)[0]

	def _set(self, kind, offset, value, little_endian=False):
		format_code, size = self._FORMATS[kind]
		position = self.byteOffset + int(offset)
		if offset < 0 or position + size > self.byteOffset + self.byteLength:
			raise JavaScriptError("DataView access is outside the view")
		if kind.startswith("Uint"):
			value = int(value) % (1 << (size * 8))
		elif kind.startswith("Int"):
			bits = size * 8
			value = int(value) % (1 << bits)
			if value >= (1 << (bits - 1)):
				value -= 1 << bits
		order = "<" if little_endian else ">"
		struct.pack_into(order + format_code, self.buffer._data, position, value)


def _make_dataview_accessor(kind, writing=False):
	if writing:
		def setter(self, offset, value, little_endian=False):
			return self._set(kind, offset, value, little_endian)
		return setter
	def getter(self, offset, little_endian=False):
		return self._get(kind, offset, little_endian)
	return getter


for _kind in DataView._FORMATS:
	setattr(DataView, "get" + _kind, _make_dataview_accessor(_kind))
	setattr(DataView, "set" + _kind, _make_dataview_accessor(_kind, True))


class TypedArray:
	_FORMAT = "B"
	_BYTES = 1
	_CLAMP = False

	def __init__(self, source=0, byte_offset=0, length=None):
		if isinstance(source, ArrayBuffer):
			self.buffer = source
			self.byteOffset = int(byte_offset)
			if self.byteOffset < 0 or self.byteOffset % self._BYTES:
				raise JavaScriptError("TypedArray offset is not aligned")
			available = source.byteLength - self.byteOffset
			self.length = available // self._BYTES if length is None else int(length)
			if self.length < 0 or self.byteOffset + self.length * self._BYTES > source.byteLength:
				raise JavaScriptError("TypedArray range is outside the buffer")
		elif isinstance(source, int):
			if source < 0:
				raise JavaScriptError("TypedArray length must not be negative")
			self.buffer = ArrayBuffer(source * self._BYTES)
			self.byteOffset = 0
			self.length = source
		else:
			values = list(source)
			self.buffer = ArrayBuffer(len(values) * self._BYTES)
			self.byteOffset = 0
			self.length = len(values)
			for index, value in enumerate(values):
				self[index] = value

	@property
	def byteLength(self):
		return self.length * self._BYTES

	def __len__(self):
		return self.length

	def __iter__(self):
		for index in range(self.length):
			yield self[index]

	def __getitem__(self, index):
		if isinstance(index, slice):
			return [self[position] for position in range(*index.indices(self.length))]
		index = int(index)
		if index < 0 or index >= self.length:
			return UNDEFINED
		return struct.unpack_from("<" + self._FORMAT, self.buffer._data, self.byteOffset + index * self._BYTES)[0]

	def __setitem__(self, index, value):
		if isinstance(index, slice):
			positions = list(range(*index.indices(self.length)))
			values = list(value)
			if len(positions) != len(values):
				raise JavaScriptError("TypedArray slice assignment cannot change its length")
			for position, item in zip(positions, values):
				self[position] = item
			return
		index = int(index)
		if index < 0 or index >= self.length:
			return
		if self._CLAMP:
			value = min(255, max(0, int(round(float(value)))))
		elif self._FORMAT in ("B", "H", "I"):
			value = int(value) % (1 << (8 * self._BYTES))
		struct.pack_into("<" + self._FORMAT, self.buffer._data, self.byteOffset + index * self._BYTES, value)

	def set(self, values, offset=0):
		offset = int(offset)
		values = list(values)
		if offset < 0 or offset + len(values) > self.length:
			raise JavaScriptError("Source array is too large")
		for index, value in enumerate(values):
			self[offset + index] = value

	def subarray(self, begin=0, end=None):
		begin = _normalize_index(begin, self.length)
		end = self.length if end is None else _normalize_index(end, self.length)
		return type(self)(self.buffer, self.byteOffset + begin * self._BYTES, max(0, end - begin))

	def slice(self, begin=0, end=None):
		view = self.subarray(begin, end)
		return type(self)(list(view))

	def fill(self, value, start=0, end=None):
		start = _normalize_index(start, self.length)
		end = self.length if end is None else _normalize_index(end, self.length)
		for index in range(start, end):
			self[index] = value
		return self

	@classmethod
	def from_(cls, values):
		return cls(list(values))

	@classmethod
	def of(cls, *values):
		return cls(values)

	def __getattr__(self, name):
		if name.isdigit():
			return self[int(name)]
		raise AttributeError(name)

	def __setattr__(self, name, value):
		if name.isdigit():
			self[int(name)] = value
		else:
			object.__setattr__(self, name, value)


def _normalize_index(index, length):
	index = int(index)
	return min(length, max(0, length + index if index < 0 else index))


def _typed_array_type(name, format_code, byte_size, clamp=False):
	return type(name, (TypedArray,), {"_FORMAT": format_code, "_BYTES": byte_size, "_CLAMP": clamp})


Int8Array = _typed_array_type("Int8Array", "b", 1)
Uint8Array = _typed_array_type("Uint8Array", "B", 1)
Uint8ClampedArray = _typed_array_type("Uint8ClampedArray", "B", 1, True)
Int16Array = _typed_array_type("Int16Array", "h", 2)
Uint16Array = _typed_array_type("Uint16Array", "H", 2)
Int32Array = _typed_array_type("Int32Array", "i", 4)
Uint32Array = _typed_array_type("Uint32Array", "I", 4)
Float32Array = _typed_array_type("Float32Array", "f", 4)
Float64Array = _typed_array_type("Float64Array", "d", 8)


class ImageData:
	def __init__(self, width, height=None, data=None):
		if isinstance(width, Uint8ClampedArray):
			pixels = width
			width = int(height)
			if data is None:
				raise JavaScriptError("ImageData(data, width, height) needs a height")
			height = int(data)
			data = pixels
		self.width = int(width)
		self.height = int(height)
		if self.width < 0 or self.height < 0:
			raise JavaScriptError("ImageData dimensions must not be negative")
		self.data = data if isinstance(data, Uint8ClampedArray) else Uint8ClampedArray(self.width * self.height * 4 if data is None else data)
		if len(self.data) != self.width * self.height * 4:
			raise JavaScriptError("ImageData buffer has the wrong length")


class CanvasSurface:
	_MAX_PIXELS = 16_777_216

	def __init__(self, width=300, height=150):
		self._width = 0
		self._height = 0
		self._pixels = bytearray()
		self._context = None
		self.width = width
		self.height = height

	@property
	def width(self):
		return self._width

	@width.setter
	def width(self, value):
		self._resize(int(value), self._height or 150)

	@property
	def height(self):
		return self._height

	@height.setter
	def height(self, value):
		self._resize(self._width or 300, int(value))

	@property
	def pixels(self):
		return self._pixels

	def _resize(self, width, height):
		width = max(0, width)
		height = max(0, height)
		if width * height > self._MAX_PIXELS:
			raise JavaScriptError("Canvas is too large")
		self._width = width
		self._height = height
		self._pixels = bytearray(width * height * 4)
		self._context = None

	def getContext(self, context_type, options=None):
		if str(context_type).lower() not in ("2d", "2d-layers"):
			return None
		if self._context is None:
			self._context = CanvasRenderingContext2D(self)
		return self._context

	def toDataURL(self, mime_type="image/png"):
		if mime_type not in ("image/png", "image/x-png"):
			return "data:image/png;base64," + base64.b64encode(self._encode_png()).decode("ascii")
		return "data:image/png;base64," + base64.b64encode(self._encode_png()).decode("ascii")

	def toBlob(self, callback, mime_type="image/png", quality=None):
		if callable(callback):
			callback(CanvasBlob(bytes(self._encode_png()), "image/png"))

	def _encode_png(self):
		def chunk(kind, data):
			payload = kind + data
			return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xffffffff)

		rows = bytearray()
		stride = self._width * 4
		for row in range(self._height):
			rows.append(0)
			start = row * stride
			rows.extend(self._pixels[start:start + stride])
		header = struct.pack(">IIBBBBB", self._width, self._height, 8, 6, 0, 0, 0)
		return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class CanvasBlob:
	def __init__(self, data, mime_type="application/octet-stream"):
		self._data = bytes(data)
		self.type = str(mime_type)
		self.size = len(self._data)

	def arrayBuffer(self):
		buffer = ArrayBuffer(len(self._data))
		buffer._data[:] = self._data
		return buffer

	def text(self):
		return self._data.decode("utf-8", errors="replace")


def _canvas_color(value):
	if isinstance(value, (tuple, list)) and len(value) >= 3:
		channels = [int(value[index]) for index in range(3)]
		return tuple(min(255, max(0, channel)) for channel in channels) + (int(value[3]) if len(value) > 3 else 255,)
	value = str(value).strip().lower()
	named = {"black": (0, 0, 0, 255), "white": (255, 255, 255, 255), "red": (255, 0, 0, 255), "green": (0, 128, 0, 255), "blue": (0, 0, 255, 255), "transparent": (0, 0, 0, 0), "yellow": (255, 255, 0, 255), "magenta": (255, 0, 255, 255), "cyan": (0, 255, 255, 255), "gray": (128, 128, 128, 255), "grey": (128, 128, 128, 255)}
	if value in named:
		return named[value]
	if value.startswith("#"):
		raw = value[1:]
		if len(raw) in (3, 4):
			raw = "".join(char * 2 for char in raw)
		if len(raw) in (6, 8):
			channels = tuple(int(raw[index:index + 2], 16) for index in range(0, len(raw), 2))
			return channels + (255,) if len(channels) == 3 else channels
	match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)", value)
	if match:
		red, green, blue = (min(255, int(match.group(index))) for index in (1, 2, 3))
		alpha = round(float(match.group(4) or 1) * 255)
		return red, green, blue, min(255, max(0, alpha))
	return 0, 0, 0, 255


class CanvasRenderingContext2D:
	def __init__(self, canvas):
		self.canvas = canvas
		self.fillStyle = "#000000"
		self.strokeStyle = "#000000"
		self.lineWidth = 1
		self.globalAlpha = 1
		self.globalCompositeOperation = "source-over"
		self.imageSmoothingEnabled = True
		self.font = "10px sans-serif"
		self.textAlign = "start"
		self.textBaseline = "alphabetic"
		self.lineCap = "butt"
		self.lineJoin = "miter"
		self._state = []
		self._path = []
		self._subpath = []
		self._matrix = (1, 0, 0, 1, 0, 0)

	def _pixel(self, x, y, color, blend=True):
		x, y = int(x), int(y)
		if x < 0 or y < 0 or x >= self.canvas.width or y >= self.canvas.height:
			return
		offset = (y * self.canvas.width + x) * 4
		red, green, blue, alpha = color
		alpha = int(alpha * max(0, min(1, float(self.globalAlpha))))
		if blend and alpha < 255:
			destination = self.canvas.pixels[offset:offset + 4]
			dest_alpha = destination[3] / 255
			source_alpha = alpha / 255
			out_alpha = source_alpha + dest_alpha * (1 - source_alpha)
			if out_alpha:
				for channel, source in enumerate((red, green, blue)):
					red_channel = (source * source_alpha + destination[channel] * dest_alpha * (1 - source_alpha)) / out_alpha
					self.canvas.pixels[offset + channel] = int(red_channel)
			self.canvas.pixels[offset + 3] = int(out_alpha * 255)
		else:
			self.canvas.pixels[offset:offset + 4] = bytes((red, green, blue, alpha))

	def _point(self, x, y):
		a, b, c, d, e, f = self._matrix
		return a * x + c * y + e, b * x + d * y + f

	def _fill_polygon(self, points, color):
		if len(points) < 3:
			return
		minimum_y = max(0, math.floor(min(point[1] for point in points)))
		maximum_y = min(self.canvas.height - 1, math.ceil(max(point[1] for point in points)))
		for y in range(minimum_y, maximum_y + 1):
			crossings = []
			for index, first in enumerate(points):
				second = points[(index + 1) % len(points)]
				if (first[1] <= y < second[1]) or (second[1] <= y < first[1]):
					crossings.append(first[0] + (y - first[1]) * (second[0] - first[0]) / (second[1] - first[1]))
			crossings.sort()
			for index in range(0, len(crossings) - 1, 2):
				for x in range(max(0, math.ceil(crossings[index])), min(self.canvas.width, math.ceil(crossings[index + 1]))):
					self._pixel(x, y, color)

	def fillRect(self, x, y, width, height):
		points = [self._point(x, y), self._point(x + width, y), self._point(x + width, y + height), self._point(x, y + height)]
		self._fill_polygon(points, _canvas_color(self.fillStyle))

	def clearRect(self, x, y, width, height):
		left, top = self._point(x, y)
		right, bottom = self._point(x + width, y + height)
		for py in range(max(0, int(min(top, bottom))), min(self.canvas.height, math.ceil(max(top, bottom)))):
			for px in range(max(0, int(min(left, right))), min(self.canvas.width, math.ceil(max(left, right)))):
				offset = (py * self.canvas.width + px) * 4
				self.canvas.pixels[offset:offset + 4] = b"\0\0\0\0"

	def strokeRect(self, x, y, width, height):
		self.beginPath()
		self.moveTo(x, y)
		self.lineTo(x + width, y)
		self.lineTo(x + width, y + height)
		self.lineTo(x, y + height)
		self.closePath()
		self.stroke()

	def beginPath(self):
		self._path = []
		self._subpath = []

	def closePath(self):
		if self._subpath and self._subpath[-1] != self._subpath[0]:
			self._subpath.append(self._subpath[0])

	def moveTo(self, x, y):
		point = self._point(float(x), float(y))
		self._subpath = [point]
		self._path.append(self._subpath)

	def lineTo(self, x, y):
		point = self._point(float(x), float(y))
		if not self._subpath:
			self._subpath = [point]
			self._path.append(self._subpath)
		else:
			self._subpath.append(point)

	def rect(self, x, y, width, height):
		self.moveTo(x, y)
		self.lineTo(x + width, y)
		self.lineTo(x + width, y + height)
		self.lineTo(x, y + height)
		self.closePath()

	def arc(self, x, y, radius, start_angle, end_angle, counterclockwise=False):
		delta = end_angle - start_angle
		if not counterclockwise and delta < 0:
			delta += 2 * math.pi
		elif counterclockwise and delta > 0:
			delta -= 2 * math.pi
		steps = min(512, max(2, int(abs(delta) * max(radius, 1) / 3)))
		for index in range(steps + 1):
			angle = start_angle + delta * index / steps
			point_x = x + math.cos(angle) * radius
			point_y = y + math.sin(angle) * radius
			if index == 0:
				self.moveTo(point_x, point_y)
			else:
				self.lineTo(point_x, point_y)

	def stroke(self):
		color = _canvas_color(self.strokeStyle)
		for path in self._path:
			for start, end in zip(path, path[1:]):
				self._draw_line(start[0], start[1], end[0], end[1], color)

	def _draw_line(self, x0, y0, x1, y1, color):
		x0, y0, x1, y1 = map(round, (x0, y0, x1, y1))
		dx, dy = abs(x1 - x0), -abs(y1 - y0)
		sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
		error = dx + dy
		while True:
			self._pixel(x0, y0, color)
			if x0 == x1 and y0 == y1:
				break
			twice = 2 * error
			if twice >= dy:
				error += dy
				x0 += sx
			if twice <= dx:
				error += dx
				y0 += sy

	def fill(self, fill_rule="nonzero"):
		for path in self._path:
			self._fill_polygon(path, _canvas_color(self.fillStyle))

	def save(self):
		self._state.append({key: getattr(self, key) for key in ("fillStyle", "strokeStyle", "lineWidth", "globalAlpha", "font", "textAlign", "textBaseline", "imageSmoothingEnabled", "_matrix")})

	def restore(self):
		if self._state:
			for key, value in self._state.pop().items():
				setattr(self, key, value)

	def setTransform(self, a=1, b=0, c=0, d=1, e=0, f=0):
		self._matrix = tuple(map(float, (a, b, c, d, e, f)))

	def resetTransform(self):
		self._matrix = (1, 0, 0, 1, 0, 0)

	def transform(self, a, b, c, d, e, f):
		a0, b0, c0, d0, e0, f0 = self._matrix
		self._matrix = (a0*a+b0*c, a0*b+b0*d, c0*a+d0*c, c0*b+d0*d, e0*a+f0*c+e, e0*b+f0*d+f)

	def translate(self, x, y):
		self.transform(1, 0, 0, 1, x, y)

	def scale(self, x, y=None):
		y = x if y is None else y
		self.transform(x, 0, 0, y, 0, 0)

	def rotate(self, angle):
		cosine, sine = math.cos(angle), math.sin(angle)
		self.transform(cosine, sine, -sine, cosine, 0, 0)

	def createImageData(self, width, height=None):
		if isinstance(width, ImageData):
			return ImageData(width.width, width.height)
		return ImageData(int(width), int(height))

	def getImageData(self, x, y, width, height, settings=None):
		width, height = max(0, int(width)), max(0, int(height))
		image = ImageData(width, height)
		for row in range(height):
			for column in range(width):
				sx, sy = int(x) + column, int(y) + row
				if 0 <= sx < self.canvas.width and 0 <= sy < self.canvas.height:
					source = (sy * self.canvas.width + sx) * 4
					dest = (row * width + column) * 4
					image.data[dest:dest + 4] = self.canvas.pixels[source:source + 4]
		return image

	def putImageData(self, image, x, y, dirty_x=0, dirty_y=0, dirty_width=None, dirty_height=None):
		if not isinstance(image, ImageData):
			raise JavaScriptError("putImageData expects ImageData")
		dirty_width = image.width if dirty_width is None else int(dirty_width)
		dirty_height = image.height if dirty_height is None else int(dirty_height)
		for row in range(max(0, int(dirty_y)), min(image.height, int(dirty_y) + dirty_height)):
			for column in range(max(0, int(dirty_x)), min(image.width, int(dirty_x) + dirty_width)):
				dx, dy = int(x) + column, int(y) + row
				if 0 <= dx < self.canvas.width and 0 <= dy < self.canvas.height:
					source = (row * image.width + column) * 4
					dest = (dy * self.canvas.width + dx) * 4
					self.canvas.pixels[dest:dest + 4] = bytes(image.data[source:source + 4])

	def drawImage(self, image, *args):
		source = image.canvas if isinstance(image, CanvasRenderingContext2D) else image
		if isinstance(source, CanvasSurface):
			source_width, source_height, pixels = source.width, source.height, source.pixels
		elif isinstance(source, ImageData):
			source_width, source_height, pixels = source.width, source.height, source.data
		else:
			raise JavaScriptError("drawImage currently supports Canvas and ImageData")
		if len(args) == 2:
			sx, sy, sw, sh, dx, dy, dw, dh = 0, 0, source_width, source_height, args[0], args[1], source_width, source_height
		elif len(args) == 4:
			sx, sy, sw, sh, dx, dy, dw, dh = 0, 0, source_width, source_height, *args
		elif len(args) == 8:
			sx, sy, sw, sh, dx, dy, dw, dh = args
		else:
			raise JavaScriptError("drawImage expects 3, 5, or 9 arguments")
		for row in range(max(0, int(dh))):
			for column in range(max(0, int(dw))):
				source_x = int(sx + column * sw / max(1, dw))
				source_y = int(sy + row * sh / max(1, dh))
				if 0 <= source_x < source_width and 0 <= source_y < source_height:
					offset = (source_y * source_width + source_x) * 4
					self._pixel(dx + column, dy + row, tuple(pixels[offset:offset + 4]))

	def measureText(self, text):
		return {"width": len(str(text)) * 7, "actualBoundingBoxAscent": 8, "actualBoundingBoxDescent": 2}

	def fillText(self, text, x, y, max_width=None):
		return None

	def strokeText(self, text, x, y, max_width=None):
		return None


class FetchHeaders:
	def __init__(self, headers=()):
		self._headers = {str(key).lower(): str(value) for key, value in dict(headers).items()}

	def get(self, name):
		return self._headers.get(str(name).lower(), None)

	def has(self, name):
		return str(name).lower() in self._headers

	def entries(self):
		return list(self._headers.items())

	def __getitem__(self, name):
		return self.get(name)


class FetchResponse:
	def __init__(self, loop, url, status, headers, body):
		self._loop = loop
		self.url = str(url)
		self.status = int(status)
		self.statusText = "OK" if 200 <= self.status < 300 else "HTTP Error"
		self.ok = 200 <= self.status < 300
		self.headers = FetchHeaders(headers)
		self._body = bytes(body)
		self.bodyUsed = False

	def _consume(self):
		if self.bodyUsed:
			raise JavaScriptError("Response body has already been read")
		self.bodyUsed = True

	def text(self):
		self._consume()
		charset = "utf-8"
		content_type = self.headers.get("content-type") or ""
		match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.IGNORECASE)
		if match:
			charset = match.group(1)
		try:
			value = self._body.decode(charset, errors="replace")
		except LookupError:
			value = self._body.decode("utf-8", errors="replace")
		promise = JSPromise(self._loop)
		promise.resolve(value)
		return promise

	def json(self):
		promise = JSPromise(self._loop)
		try:
			promise.resolve(json.loads(self.text().value))
		except Exception as exc:
			promise.reject(exc)
		return promise

	def arrayBuffer(self):
		self._consume()
		buffer = ArrayBuffer(len(self._body))
		buffer._data[:] = self._body
		promise = JSPromise(self._loop)
		promise.resolve(buffer)
		return promise

	def clone(self):
		return FetchResponse(self._loop, self.url, self.status, self.headers.entries(), self._body)


class ResourceLoader:
	def __init__(self, loop, base_url="", timeout=15):
		self.loop = loop
		self.base_url = str(base_url)
		self.timeout = timeout

	def request(self, url, options=None):
		options = options or {}
		url = urljoin(self.base_url, str(url))
		method = str(options.get("method", "GET")).upper()
		headers = options.get("headers", {}) or {}
		body = options.get("body")
		if isinstance(body, str):
			body = body.encode("utf-8")
		elif isinstance(body, TypedArray):
			body = bytes(body)
		elif isinstance(body, ArrayBuffer):
			body = bytes(body._data)
		elif body is not None and not isinstance(body, (bytes, bytearray)):
			body = str(body).encode("utf-8")
		request = Request(url, data=body, headers=dict(headers), method=method)
		try:
			response = urlopen(request, timeout=float(options.get("timeout", self.timeout)))
		except HTTPError as response:
			pass
		return FetchResponse(
			self.loop,
			response.geturl(),
			getattr(response, "status", None) or getattr(response, "code", None) or 200,
			response.headers.items(),
			response.read(),
		)

	def fetch(self, url, options=None):
		promise = JSPromise(self.loop)
		try:
			promise.resolve(self.request(url, options))
		except Exception as exc:
			promise.reject(exc)
		return promise


class XMLHttpRequest:
	UNSENT = 0
	OPENED = 1
	HEADERS_RECEIVED = 2
	LOADING = 3
	DONE = 4

	def __init__(self, loader):
		self._event_target = EventTarget()
		self.loader = loader
		self.readyState = self.UNSENT
		self.status = 0
		self.statusText = ""
		self.responseText = ""
		self.response = None
		self.responseType = "text"
		self.timeout = loader.timeout
		self.withCredentials = False
		self.onreadystatechange = None
		self.onload = None
		self.onerror = None
		self.onprogress = None
		self._headers = {}
		self._response_headers = FetchHeaders()

	def addEventListener(self, event_type, callback, options=None):
		return self._event_target.addEventListener(event_type, callback, options)

	def removeEventListener(self, event_type, callback):
		return self._event_target.removeEventListener(event_type, callback)

	def dispatchEvent(self, event):
		return self._event_target.dispatchEvent(event)

	def _emit(self, event_type):
		self.dispatchEvent(JSEvent(event_type))
		handler = getattr(self, "on" + event_type, None)
		if callable(handler):
			handler(JSEvent(event_type))

	def _set_state(self, state):
		self.readyState = state
		self._emit("readystatechange")

	def open(self, method, url, async_=True, username=None, password=None):
		self.method = str(method).upper()
		self.url = str(url)
		self.async_ = bool(async_)
		self._headers = {}
		self._set_state(self.OPENED)

	def setRequestHeader(self, name, value):
		if self.readyState != self.OPENED:
			raise JavaScriptError("XMLHttpRequest is not opened")
		self._headers[str(name)] = str(value)

	def send(self, body=None):
		try:
			response = self.loader.request(
				self.url,
				{"method": self.method, "headers": self._headers, "body": body, "timeout": self.timeout},
			)
			self.status = response.status
			self.statusText = response.statusText
			self._response_headers = response.headers
			self._set_state(self.HEADERS_RECEIVED)
			self._set_state(self.LOADING)
			self.responseText = response._body.decode("utf-8", errors="replace")
			self.response = response._body if self.responseType == "arraybuffer" else self.responseText
			self._set_state(self.DONE)
			self._emit("load")
		except Exception:
			self._set_state(self.DONE)
			self._emit("error")

	def abort(self):
		self.status = 0
		self.response = None
		self.responseText = ""
		self._set_state(self.UNSENT)
		self._emit("abort")

	def getResponseHeader(self, name):
		return self._response_headers.get(name)

	def getAllResponseHeaders(self):
		return "\r\n".join(f"{key}: {value}" for key, value in self._response_headers.entries())


class EventLoop:
	def __init__(self):
		self.microtasks = []
		self.timers = []
		self.timer_ids = itertools.count(1)
		self.active_timers = set()
		self.now = 0
		self.errors = []
		self.timer_scheduler = None

	def set_timer_scheduler(self, scheduler):
		self.timer_scheduler = scheduler

	def queue_microtask(self, callback):
		self.microtasks.append(callback)

	def set_timeout(self, callback, delay=0, interval=0):
		timer_id = next(self.timer_ids)
		due = self.now + max(0, float(delay))
		self.active_timers.add(timer_id)
		heapq.heappush(self.timers, (due, timer_id, callback, max(0, float(interval))))
		if self.timer_scheduler:
			self.timer_scheduler(timer_id, max(0, float(delay)))
		return timer_id

	def clear_timer(self, timer_id):
		self.active_timers.discard(timer_id)
		self.timers = [timer for timer in self.timers if timer[1] != timer_id]
		heapq.heapify(self.timers)

	def run_microtasks(self, limit=10000):
		count = 0
		while self.microtasks:
			if count >= limit:
				raise JavaScriptError("Microtask execution limit exceeded")
			callback = self.microtasks.pop(0)
			try:
				callback()
			except Exception as exc:
				self.errors.append(exc)
			count += 1

	def run_next_timer(self):
		self.run_microtasks()
		while self.timers:
			due, timer_id, _, _ = self.timers[0]
			if timer_id not in self.active_timers:
				heapq.heappop(self.timers)
				continue
			return self.run_timer(timer_id)
		return False

	def run_timer(self, timer_id):
		for index, timer in enumerate(self.timers):
			if timer[1] == timer_id:
				due, _, callback, interval = self.timers.pop(index)
				heapq.heapify(self.timers)
				break
		else:
			return False
		if timer_id not in self.active_timers:
			return False
		self.now = max(self.now, due)
		if not interval:
			self.active_timers.discard(timer_id)
		try:
			callback()
		except Exception as exc:
			self.errors.append(exc)
		if interval and timer_id in self.active_timers:
			due = self.now + interval
			heapq.heappush(self.timers, (due, timer_id, callback, interval))
			if self.timer_scheduler:
				self.timer_scheduler(timer_id, interval)
		self.run_microtasks()
		return True

	def run_all(self, limit=10000):
		count = 0
		while self.timers or self.microtasks:
			if count >= limit:
				raise JavaScriptError("Timer execution limit exceeded")
			if self.timers:
				self.run_next_timer()
			else:
				self.run_microtasks()
			count += 1


class JSPromise:
	def __init__(self, loop, executor=None):
		self.loop = loop
		self.state = "pending"
		self.value = UNDEFINED
		self.handlers = []
		if executor is not None:
			try:
				executor(self.resolve, self.reject)
			except Exception as exc:
				self.reject(exc)

	def resolve(self, value=UNDEFINED):
		if self.state != "pending":
			return
		if value is self:
			self.reject(JavaScriptError("Promise cannot resolve to itself"))
			return
		if isinstance(value, JSPromise):
			value.then(self.resolve, self.reject)
			return
		self._settle("fulfilled", value)

	def reject(self, reason=UNDEFINED):
		if self.state == "pending":
			self._settle("rejected", reason)

	def _settle(self, state, value):
		self.state = state
		self.value = value
		handlers, self.handlers = self.handlers, []
		for handler in handlers:
			self.loop.queue_microtask(lambda handler=handler: self._run_handler(handler))

	def _run_handler(self, handler):
		callback = handler[0] if self.state == "fulfilled" else handler[1]
		next_promise = handler[2]
		if callback is None:
			(next_promise.resolve if self.state == "fulfilled" else next_promise.reject)(self.value)
			return
		try:
			next_promise.resolve(callback(self.value))
		except Exception as exc:
			next_promise.reject(exc)

	def then(self, on_fulfilled=None, on_rejected=None):
		next_promise = JSPromise(self.loop)
		handler = (on_fulfilled, on_rejected, next_promise)
		if self.state == "pending":
			self.handlers.append(handler)
		else:
			self.loop.queue_microtask(lambda: self._run_handler(handler))
		return next_promise

	def catch(self, on_rejected):
		return self.then(None, on_rejected)

	def finally_(self, callback):
		def fulfilled(value):
			result = callback()
			return result.then(lambda _: value) if isinstance(result, JSPromise) else value

		def rejected(reason):
			result = callback()
			if isinstance(result, JSPromise):
				return result.then(lambda _: _raise(reason))
			return _raise(reason)

		return self.then(fulfilled, rejected)

	def wait(self, limit=10000):
		count = 0
		while self.state == "pending":
			self.loop.run_microtasks()
			if self.state != "pending":
				break
			if count >= limit or not self.loop.run_next_timer() and self.state == "pending":
				raise JavaScriptError("Promise is still pending")
			count += 1
		self.loop.run_microtasks()
		if self.state == "rejected":
			if isinstance(self.value, Exception):
				raise self.value
			raise JavaScriptError(str(self.value))
		return self.value


def _raise(error):
	raise error if isinstance(error, Exception) else JavaScriptError(str(error))


class PromiseConstructor:
	def __init__(self, loop):
		self.loop = loop

	def __call__(self, executor):
		return JSPromise(self.loop, executor)

	def resolve(self, value=UNDEFINED):
		promise = JSPromise(self.loop)
		promise.resolve(value)
		return promise

	def reject(self, reason=UNDEFINED):
		promise = JSPromise(self.loop)
		promise.reject(reason)
		return promise

	def all(self, values):
		values = list(values)
		result = JSPromise(self.loop)
		if not values:
			result.resolve([])
			return result
		resolved = [UNDEFINED] * len(values)
		remaining = [len(values)]
		for index, value in enumerate(values):
			self.resolve(value).then(
				lambda item, index=index: _promise_all_item(result, resolved, remaining, index, item),
				result.reject,
			)
		return result

	def race(self, values):
		result = JSPromise(self.loop)
		for value in values:
			self.resolve(value).then(result.resolve, result.reject)
		return result


def _promise_all_item(result, resolved, remaining, index, value):
	resolved[index] = value
	remaining[0] -= 1
	if remaining[0] == 0:
		result.resolve(resolved)
	return UNDEFINED


class JSEvent:
	def __init__(self, event_type, options=None):
		options = options or {}
		self.type = str(event_type)
		self.bubbles = bool(options.get("bubbles", False))
		self.cancelable = bool(options.get("cancelable", False))
		self.defaultPrevented = False
		self.propagationStopped = False
		self.immediatePropagationStopped = False
		self.target = None
		self.currentTarget = None

	def preventDefault(self):
		if self.cancelable:
			self.defaultPrevented = True

	def stopPropagation(self):
		self.propagationStopped = True

	def stopImmediatePropagation(self):
		self.propagationStopped = True
		self.immediatePropagationStopped = True


class EventTarget:
	def __init__(self):
		self.listeners = {}

	def addEventListener(self, event_type, callback, options=None):
		if not callable(callback):
			return
		options = options or {}
		if isinstance(options, bool):
			options = {"once": options}
		self.listeners.setdefault(str(event_type), []).append((callback, bool(options.get("once", False))))

	def removeEventListener(self, event_type, callback):
		self.listeners[str(event_type)] = [
			entry for entry in self.listeners.get(str(event_type), []) if entry[0] is not callback
		]

	def dispatchEvent(self, event):
		if isinstance(event, str):
			event = JSEvent(event)
		if not isinstance(event, JSEvent):
			raise JavaScriptError("dispatchEvent expects an Event")
		if event.target is None:
			event.target = self
		event.currentTarget = self
		listeners = list(self.listeners.get(event.type, []))
		for callback, once in listeners:
			callback(event)
			if once:
				self.removeEventListener(event.type, callback)
			if event.immediatePropagationStopped:
				break
		return not event.defaultPrevented
