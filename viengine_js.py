import json
import math
import re
from typing import Optional, Dict, Any

try:  # нативный Zig-движок (vijs_engine/src) — опционально
	from vijs_bridge import get_bridge as _get_native_bridge
except Exception:  # pragma: no cover - деградация на Python-движок
	_get_native_bridge = None

from viengine_js_else import (
	ArrayBuffer,
	CanvasSurface,
	DataView,
	EventLoop,
	EventTarget,
	JSEvent,
	JSPromise,
	JavaScriptError,
	PromiseConstructor,
	ResourceLoader,
	UNDEFINED,
	XMLHttpRequest,
	Float32Array,
	Float64Array,
	Int8Array,
	Int16Array,
	Int32Array,
	Uint8Array,
	Uint8ClampedArray,
	Uint16Array,
	Uint32Array,
)


class Environment:
	def __init__(self, parent=None, values=None):
		self.parent = parent
		self.values = values if values is not None else {}

	def declare(self, name, value=UNDEFINED):
		self.values[name] = value
		return value

	def get(self, name):
		if name in self.values:
			return self.values[name]
		if self.parent:
			return self.parent.get(name)
		raise JavaScriptError(f"'{name}' is not defined")

	def assign(self, name, value):
		if name in self.values:
			self.values[name] = value
		elif self.parent:
			self.parent.assign(name, value)
		else:
			self.values[name] = value
		return value


class _Return(Exception):
	def __init__(self, value):
		self.value = value


class _Function:
	def __init__(self, engine, parameters, body, closure, is_async=False):
		self.engine = engine
		self.parameters = parameters
		self.body = body
		self.closure = closure
		self.is_async = is_async

	def __call__(self, *arguments):
		if self.is_async:
			promise = JSPromise(self.engine.event_loop)
			try:
				promise.resolve(self._invoke(arguments))
			except Exception as exc:
				promise.reject(exc)
			return promise
		return self._invoke(arguments)

	def _invoke(self, arguments):
		scope = Environment(self.closure)
		for index, name in enumerate(self.parameters):
			scope.declare(name, arguments[index] if index < len(arguments) else UNDEFINED)
		try:
			return self.engine._statement(self.body, scope)
		except _Return as returned:
			return returned.value


class _Parser:
	_PRECEDENCE = {
			"=": 1, "+=": 1, "-=": 1,
			"||": 3, "??": 3, "&&": 4,
			"==": 5, "!=": 5, "===": 5, "!==": 5,
			"<": 6, ">": 6, "<=": 6, ">=": 6,
			"+": 7, "-": 7,
			"*": 8, "/": 8, "%": 8,
	}

	def __init__(self, source):
		self.tokens = self._tokenize(source)
		self.position = 0

	def _tokenize(self, source):
		tokens = []
		operators = ("===", "!==", "=>", "==", "!=", "<=", ">=", "&&", "||", "??", "++", "--", "+=", "-=")
		index = 0
		while index < len(source):
			char = source[index]
			if char.isspace():
				index += 1
				continue
			if source.startswith("//", index):
				newline = source.find("\n", index)
				index = len(source) if newline < 0 else newline + 1
				continue
			if source.startswith("/*", index):
				end = source.find("*/", index + 2)
				if end < 0:
					raise JavaScriptError("Unclosed block comment")
				index = end + 2
				continue
			if char in "'\"`":
				quote = char
				index += 1
				value = []
				while index < len(source) and source[index] != quote:
					if source[index] == "\\" and index + 1 < len(source):
						index += 1
						escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
						value.append(escapes.get(source[index], source[index]))
					else:
						value.append(source[index])
					index += 1
				if index >= len(source):
					raise JavaScriptError("Unclosed string")
				index += 1
				tokens.append(("string", "".join(value)))
				continue
			number = re.match(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?", source[index:])
			if number:
				value = number.group(0)
				tokens.append(("number", float(value) if any(ch in value for ch in ".eE") else int(value)))
				index += len(value)
				continue
			identifier = re.match(r"[A-Za-z_$][\w$]*", source[index:])
			if identifier:
				value = identifier.group(0)
				tokens.append(("identifier", value))
				index += len(value)
				continue
			operator = next((item for item in operators if source.startswith(item, index)), None)
			if operator:
				tokens.append(("operator", operator))
				index += len(operator)
				continue
			if char in "{}[]();,.:?+-*/%=!<>":
				tokens.append(("operator", char))
				index += 1
				continue
			raise JavaScriptError(f"Unexpected character {char!r} at {index}")
		tokens.append(("eof", ""))
		return tokens

	def _value(self, offset=0):
		return self.tokens[min(self.position + offset, len(self.tokens) - 1)][1]

	def _take(self):
		token = self.tokens[self.position]
		self.position += 1
		return token

	def _match(self, *values):
		if self._value() in values:
			return self._take()[1]
		return None

	def _expect(self, value):
		actual = self._take()[1]
		if actual != value:
			raise JavaScriptError(f"Expected {value!r}, got {actual!r}")

	def parse(self):
		statements = []
		while self.tokens[self.position][0] != "eof":
			old_position = self.position
			statements.append(self._statement())
			if self.position == old_position:
				raise JavaScriptError("Parser made no progress")
		return ("block", statements)

	def _statement(self):
		if self._match(";"):
			return ("empty",)
		if self._match("{"):
			statements = []
			while self._value() != "}":
				if self.tokens[self.position][0] == "eof":
					raise JavaScriptError("Unclosed block")
				statements.append(self._statement())
			self._expect("}")
			return ("block", statements)
		if self._value() in ("let", "const", "var"):
			return self._variables(True)
		if self._value() == "async" and self._value(1) == "function":
			self._take()
			self._take()
			name = self._take()[1]
			parameters, body = self._function_tail()
			return ("function_decl", name, parameters, body, True)
		if self._match("function"):
			name = self._take()[1]
			parameters, body = self._function_tail()
			return ("function_decl", name, parameters, body, False)
		if self._match("return"):
			value = None if self._value() in (";", "}", "") else self._expression()
			self._match(";")
			return ("return", value)
		if self._match("if"):
			self._expect("(")
			condition = self._expression()
			self._expect(")")
			consequent = self._statement()
			alternate = self._statement() if self._match("else") else None
			return ("if", condition, consequent, alternate)
		if self._match("while"):
			self._expect("(")
			condition = self._expression()
			self._expect(")")
			return ("while", condition, self._statement())
		if self._match("for"):
			self._expect("(")
			initializer = None
			if self._value() != ";":
				initializer = self._variables(False) if self._value() in ("let", "const", "var") else self._expression()
			self._expect(";")
			condition = None if self._value() == ";" else self._expression()
			self._expect(";")
			update = None if self._value() == ")" else self._expression()
			self._expect(")")
			return ("for", initializer, condition, update, self._statement())
		expression = self._expression()
		self._match(";")
		return ("expression", expression)

	def _variables(self, semicolon):
		self._take()
		declarations = []
		while True:
			name = self._take()[1]
			if self.tokens[self.position - 1][0] != "identifier":
				raise JavaScriptError("Expected variable name")
			value = self._expression(2) if self._match("=") else None
			declarations.append((name, value))
			if not self._match(","):
				break
		if semicolon:
			self._match(";")
		return ("variables", declarations)

	def _function_tail(self):
		self._expect("(")
		parameters = []
		if self._value() != ")":
			while True:
				parameters.append(self._take()[1])
				if not self._match(","):
					break
		self._expect(")")
		body = self._statement()
		if body[0] != "block":
			raise JavaScriptError("Function body must be a block")
		return parameters, body

	def _expression(self, minimum=1):
		left = self._prefix()
		while True:
			operator = self._value()
			if operator == ".":
				self._take()
				left = ("member", left, ("literal", self._take()[1]))
				continue
			if operator == "[":
				self._take()
				key = self._expression()
				self._expect("]")
				left = ("member", left, key)
				continue
			if operator == "(":
				self._take()
				arguments = []
				if self._value() != ")":
					while True:
						arguments.append(self._expression(2))
						if not self._match(","):
							break
				self._expect(")")
				left = ("call", left, arguments)
				continue
			if operator in ("++", "--"):
				self._take()
				left = ("update", operator, left, False)
				continue
			if operator == "?" and minimum <= 2:
				self._take()
				yes = self._expression()
				self._expect(":")
				no = self._expression(2)
				left = ("conditional", left, yes, no)
				continue
			precedence = self._PRECEDENCE.get(operator, 0)
			if precedence < minimum:
				break
			self._take()
			right = self._expression(precedence if precedence == 1 else precedence + 1)
			left = ("assign", operator, left, right) if precedence == 1 else ("binary", operator, left, right)
		return left

	def _prefix(self):
		token_type, value = self._take()
		if value in ("!", "-", "+"):
			return ("unary", value, self._expression(9))
		if value in ("++", "--"):
			return ("update", value, self._prefix(), True)
		if value == "typeof":
			return ("unary", value, self._expression(9))
		if value == "await":
			return ("await", self._expression(9))
		if token_type == "number" or token_type == "string":
			return ("literal", value)
		if token_type == "identifier":
			if value == "true":
				return ("literal", True)
			if value == "false":
				return ("literal", False)
			if value == "null":
				return ("literal", None)
			if value == "undefined":
				return ("literal", UNDEFINED)
			if value == "function":
				if self.tokens[self.position][0] == "identifier":
					self._take()
				parameters, body = self._function_tail()
				return ("function", parameters, body, False)
			if value == "async":
				if self._match("function"):
					if self.tokens[self.position][0] == "identifier":
						self._take()
					parameters, body = self._function_tail()
					return ("function", parameters, body, True)
				if self._match("("):
					parameters = []
					if self._value() != ")":
						while True:
							parameters.append(self._take()[1])
							if not self._match(","):
								break
					self._expect(")")
					self._expect("=>")
					body = self._statement() if self._value() == "{" else ("return", self._expression())
					return ("function", parameters, body, True)
				if self.tokens[self.position][0] == "identifier":
					parameter = self._take()[1]
					if self._match("=>"):
						body = self._statement() if self._value() == "{" else ("return", self._expression())
						return ("function", [parameter], body, True)
				return ("identifier", value)
			if value == "new":
				constructor = self._prefix()
				arguments = []
				if self._match("("):
					if self._value() != ")":
						while True:
							arguments.append(self._expression(2))
							if not self._match(","):
								break
					self._expect(")")
				return ("new", ("call", constructor, arguments))
				raise JavaScriptError("new requires a constructor call")
			if self._match("=>"):
				body = self._statement() if self._value() == "{" else ("return", self._expression())
				return ("function", [value], body, False)
			return ("identifier", value)
		if value == "(":
			saved = self.position
			try:
				parameters = []
				if self._value() != ")":
					while True:
						if self.tokens[self.position][0] != "identifier":
							raise JavaScriptError("Not an arrow parameter list")
						parameters.append(self._take()[1])
						if not self._match(","):
							break
				self._expect(")")
				if not self._match("=>"):
					raise JavaScriptError("Not an arrow function")
				body = self._statement() if self._value() == "{" else ("return", self._expression())
				return ("function", parameters, body, False)
			except JavaScriptError:
				self.position = saved
			expression = self._expression()
			self._expect(")")
			return expression
		if value == "[":
			items = []
			while self._value() != "]":
				items.append(self._expression(2))
				if not self._match(","):
					break
			self._expect("]")
			return ("array", items)
		if value == "{":
			properties = []
			while self._value() != "}":
				key = self._take()[1]
				if self._match(":"):
					value_expression = self._expression(2)
				else:
					value_expression = ("identifier", key)
				properties.append((key, value_expression))
				if not self._match(","):
					break
			self._expect("}")
			return ("object", properties)
		raise JavaScriptError(f"Unexpected token {value!r}")


_NATIVE_BINARY_OPS = frozenset(("*", "/", "%"))


class JavaScriptEngine:
	def __init__(self, max_steps=100000):
		self.max_steps = max_steps
		self.steps = 0
		self.globals = None
		self.event_loop = EventLoop()
		# Нативный ускоритель (vijs_engine): hot-path арифметику считает он;
		# если .so/.dll не собрана — молча работаем на Python-движке.
		self.native_bridge = _get_native_bridge() if _get_native_bridge else None
		self.native_hits = 0
		self.native_misses = 0

	def execute(self, source, globals=None):
		if not isinstance(source, str):
			raise TypeError("JavaScript source must be a string")
		self.steps = 0
		environment = self.globals
		if environment is None:
			environment = Environment(values=self._builtins())
			self.globals = environment
		if globals:
			environment.values.update(globals)
		program = _Parser(source).parse()
		try:
			result = self._statement(program, environment)
		except _Return as returned:
			result = returned.value
		self.event_loop.run_microtasks()
		return result

	def run_timers(self, limit=10000):
		self.event_loop.run_all(limit)

	def _builtins(self):
		loop = self.event_loop
		promise_constructor = PromiseConstructor(loop)
		resource_loader = ResourceLoader(loop)

		def fetch_resource(url, options=None):
			if self.globals is not None:
				location = self.globals.values.get("location", {})
				if isinstance(location, dict):
					resource_loader.base_url = location.get("href", resource_loader.base_url)
			return resource_loader.fetch(url, options)

		def xhr_constructor():
			return XMLHttpRequest(resource_loader)

		for array_type in (
				Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array,
				Int32Array, Uint32Array, Float32Array, Float64Array,
		):
			array_type.BYTES_PER_ELEMENT = array_type._BYTES
			setattr(array_type, "from", classmethod(lambda cls, values: cls.from_(values)))
		math_object = {
				"PI": math.pi, "E": math.e,
				"abs": abs, "floor": math.floor, "ceil": math.ceil,
				"round": round, "sqrt": math.sqrt,
				"max": max, "min": min, "pow": pow,
		}
		json_object = {"parse": json.loads, "stringify": json.dumps}
		return {
				"Math": math_object, "JSON": json_object,
				"Promise": promise_constructor,
				"Event": JSEvent, "EventTarget": EventTarget,
				"ArrayBuffer": ArrayBuffer, "DataView": DataView,
				"Int8Array": Int8Array, "Uint8Array": Uint8Array,
				"Uint8ClampedArray": Uint8ClampedArray,
				"Int16Array": Int16Array, "Uint16Array": Uint16Array,
				"Int32Array": Int32Array, "Uint32Array": Uint32Array,
				"Float32Array": Float32Array, "Float64Array": Float64Array,
				"OffscreenCanvas": CanvasSurface, "fetch": fetch_resource,
				"XMLHttpRequest": xhr_constructor,
				"setTimeout": lambda callback, delay=0, *args: loop.set_timeout(lambda: callback(*args), delay),
				"clearTimeout": loop.clear_timer,
				"setInterval": lambda callback, delay=0, *args: loop.set_timeout(lambda: callback(*args), delay, max(1, float(delay))),
				"clearInterval": loop.clear_timer,
				"requestAnimationFrame": lambda callback: loop.set_timeout(lambda: callback(loop.now), 16),
				"cancelAnimationFrame": loop.clear_timer,
				"queueMicrotask": loop.queue_microtask,
				"parseInt": lambda value, radix=10: int(str(value), radix),
				"parseFloat": float, "Number": float, "String": str,
				"Boolean": self._truthy,
				"isNaN": lambda value: isinstance(value, float) and math.isnan(value),
		}

	def _literal_number(self, node):
		"""True, если узел — числовой литерал."""
		if isinstance(node, tuple) and len(node) == 2 and node[0] == "literal":
			value = node[1]
			if isinstance(value, (int, float)) and not isinstance(value, bool):
				return True
		return False

	def _native_eval_binary(self, operator, left_node, right_node):
		"""Вычисляет a op b нативным Zig-движком vijs_engine.

		Возвращает float либо None — тогда считаем на Python. Используем
		движок только когда оба операнда — числовые литералы и оператор
		не '+', чтобы семантика совпадала с _binary() один в один.
		"""
		bridge = self.native_bridge
		if bridge is None or not bridge.is_native:
			return None
		if operator not in _NATIVE_BINARY_OPS:
			return None
		if not (self._literal_number(left_node) and self._literal_number(right_node)):
			return None
		source = f"{left_node[1]} {operator} {right_node[1]}"
		result = bridge.eval_arithmetic(source)
		if result is None:
			self.native_misses += 1
		else:
			self.native_hits += 1
		return result

	def _tick(self):
		self.steps += 1
		if self.steps > self.max_steps:
			raise JavaScriptError("Execution limit exceeded")

	def _statement(self, node, environment):
		self._tick()
		kind = node[0]
		if kind in ("empty",):
			return UNDEFINED
		if kind == "block":
			result = UNDEFINED
			for statement in node[1]:
				result = self._statement(statement, environment)
			return result
		if kind == "expression":
			return self._expression(node[1], environment)
		if kind == "variables":
			result = UNDEFINED
			for name, initializer in node[1]:
				result = environment.declare(name, self._expression(initializer, environment) if initializer else UNDEFINED)
			return result
		if kind == "function_decl":
			function = _Function(self, node[2], node[3], environment, node[4])
			environment.declare(node[1], function)
			return function
		if kind == "return":
			raise _Return(self._expression(node[1], environment) if node[1] else UNDEFINED)
		if kind == "if":
			branch = node[2] if self._truthy(self._expression(node[1], environment)) else node[3]
			return self._statement(branch, environment) if branch else UNDEFINED
		if kind == "while":
			result = UNDEFINED
			while self._truthy(self._expression(node[1], environment)):
				result = self._statement(node[2], environment)
				self._tick()
			return result
		if kind == "for":
			if node[1]:
				self._statement(node[1], environment) if isinstance(node[1], tuple) and node[1][0] in ("variables", "block", "expression") else self._expression(node[1], environment)
			result = UNDEFINED
			while node[2] is None or self._truthy(self._expression(node[2], environment)):
				result = self._statement(node[4], environment)
				if node[3]:
					self._expression(node[3], environment)
				self._tick()
			return result
		raise JavaScriptError(f"Unsupported statement {kind}")

	def _expression(self, node, environment):
		self._tick()
		kind = node[0]
		if kind == "literal":
			return node[1]
		if kind == "identifier":
			return environment.get(node[1])
		if kind == "array":
			return [self._expression(item, environment) for item in node[1]]
		if kind == "object":
			return {key: self._expression(value, environment) for key, value in node[1]}
		if kind == "function":
			return _Function(self, node[1], node[2], environment, node[3])
		if kind == "member":
			return self._get_member(self._expression(node[1], environment), self._expression(node[2], environment))
		if kind == "call":
			function = self._expression(node[1], environment)
			arguments = [self._expression(argument, environment) for argument in node[2]]
			if not callable(function):
				raise JavaScriptError("Value is not callable")
			return function(*arguments)
		if kind == "new":
			call_expression = node[1]
			constructor = self._expression(call_expression[1], environment)
			arguments = [self._expression(argument, environment) for argument in call_expression[2]]
			if not callable(constructor):
				raise JavaScriptError("Value is not a constructor")
			return constructor(*arguments)
		if kind == "unary":
			value = self._expression(node[2], environment)
			if node[1] == "!":
				return not self._truthy(value)
			if node[1] == "-":
				return -self._number(value)
			if node[1] == "+":
				return self._number(value)
			if node[1] == "typeof":
				if value is UNDEFINED:
					return "undefined"
				if callable(value):
					return "function"
				if isinstance(value, bool):
					return "boolean"
				if isinstance(value, (int, float)):
					return "number"
				return "object" if value is None or isinstance(value, (dict, list)) else "string"
		if kind == "binary":
			operator = node[1]
			left = self._expression(node[2], environment)
			if operator == "&&":
				return self._expression(node[3], environment) if self._truthy(left) else left
			if operator == "||":
				return left if self._truthy(left) else self._expression(node[3], environment)
			if operator == "??":
				return self._expression(node[3], environment) if left is None or left is UNDEFINED else left
			native = self._native_eval_binary(operator, node[2], node[3])
			if native is not None:
				return native
			right = self._expression(node[3], environment)
			return self._binary(operator, left, right)
		if kind == "conditional":
			return self._expression(node[2] if self._truthy(self._expression(node[1], environment)) else node[3], environment)
		if kind == "assign":
			operator, target, value_node = node[1], node[2], node[3]
			value = self._expression(value_node, environment)
			if operator != "=":
				old_value = self._read_target(target, environment)
				value = self._binary(operator[0], old_value, value)
			return self._write_target(target, value, environment)
		if kind == "update":
			old_value = self._number(self._read_target(node[2], environment))
			new_value = old_value + (1 if node[1] == "++" else -1)
			self._write_target(node[2], new_value, environment)
			return new_value if node[3] else old_value
		if kind == "await":
			value = self._expression(node[1], environment)
			return value.wait() if isinstance(value, JSPromise) else value
		raise JavaScriptError(f"Unsupported expression {kind}")

	def _read_target(self, target, environment):
		if target[0] == "identifier":
			return environment.get(target[1])
		if target[0] == "member":
			return self._get_member(self._expression(target[1], environment), self._expression(target[2], environment))
		raise JavaScriptError("Invalid assignment target")

	def _write_target(self, target, value, environment):
		if target[0] == "identifier":
			return environment.assign(target[1], value)
		if target[0] == "member":
			owner = self._expression(target[1], environment)
			key = self._expression(target[2], environment)
			if isinstance(owner, dict):
				owner[str(key)] = value
			elif isinstance(owner, list):
				if key == "length":
					del owner[int(value):]
				else:
					index = int(key)
					while len(owner) <= index:
						owner.append(UNDEFINED)
					owner[index] = value
			else:
					try:
						setattr(owner, str(key), value)
					except (AttributeError, TypeError) as exc:
						raise JavaScriptError("Cannot assign property") from exc
			return value
		raise JavaScriptError("Invalid assignment target")

	def _get_member(self, owner, key):
		key = str(key)
		if isinstance(owner, dict):
			return owner.get(key, UNDEFINED)
		if isinstance(owner, (list, str)):
			if key == "length":
				return len(owner)
			if isinstance(owner, list) and key == "push":
				return lambda *items: (owner.extend(items), len(owner))[1]
			if isinstance(owner, list) and key == "pop":
				return lambda: owner.pop() if owner else UNDEFINED
			if isinstance(owner, str) and key == "includes":
				return lambda item: str(item) in owner
			try:
				return owner[int(key)]
			except (ValueError, IndexError):
				return UNDEFINED
		if isinstance(owner, JSPromise) and key == "finally":
			return owner.finally_
		try:
			return getattr(owner, key)
		except AttributeError:
			return UNDEFINED

	def _binary(self, operator, left, right):
		if operator == "+":
			if isinstance(left, str) or isinstance(right, str):
				return self._string(left) + self._string(right)
			return self._number(left) + self._number(right)
		if operator == "-":
			return self._number(left) - self._number(right)
		if operator == "*":
			return self._number(left) * self._number(right)
		if operator == "/":
			return self._number(left) / self._number(right)
		if operator == "%":
			return self._number(left) % self._number(right)
		if operator in ("==", "==="):
			if operator == "===":
				if isinstance(left, bool) or isinstance(right, bool):
					return type(left) is type(right) and left == right
				if isinstance(left, (int, float)) and isinstance(right, (int, float)):
					return left == right
				return type(left) is type(right) and left == right
			return left == right or str(left) == str(right)
		if operator in ("!=", "!=="):
			return not self._binary("==" if operator == "!=" else "===", left, right)
		if operator == "<":
			return left < right
		if operator == ">":
			return left > right
		if operator == "<=":
			return left <= right
		if operator == ">=":
			return left >= right
		raise JavaScriptError(f"Unsupported operator {operator}")

	def _truthy(self, value):
		return not (value is UNDEFINED or value is None or value is False or value == 0 or value == "")

	def _number(self, value):
		if value is UNDEFINED:
			return math.nan
		if value is None:
			return 0
		if isinstance(value, bool):
			return int(value)
		return float(value)

	def _string(self, value):
		if value is UNDEFINED:
			return "undefined"
		if value is None:
			return "null"
		if value is True:
			return "true"
		if value is False:
			return "false"
		if isinstance(value, float) and value.is_integer():
			return str(int(value))
		return str(value)
	
def _parse_string(self, quote_char: str) -> Dict[str, Any]:
        end = self.code.find(quote_char, self.pos + 1)
        if end < 0:
            raise JavaScriptError("Unterminated string literal")
        val = self.code[self.pos + 1:end]
        self.pos = end + 1
        return {"type": "Literal", "value": val}

def _parse_identifier_or_keyword(self) -> Dict[str, Any]:
        start = self.pos
        while self.pos < len(self.code) and (self.code[self.pos].isalnum() or self.code[self.pos] in "_$"):
            self.pos += 1
        name = self.code[start:self.pos]

        if name in ("true", "false"):
            return {"type": "Literal", "value": name == "true"}
        elif name == "null":
            return {"type": "Literal", "value": None}
        elif name == "undefined":
            return {"type": "Identifier", "name": "undefined"}

        return {"type": "Identifier", "name": name}

def parse_expression(self) -> Dict[str, Any]:
        self._skip_whitespace()
        if self.pos >= len(self.code):
            return {"type": "Empty"}

        char = self.code[self.pos]

        if char in ("'", '"', '`'):
            return self._parse_string(char)

        if char.isdigit():
            start = self.pos
            while self.pos < len(self.code) and (self.code[self.pos].isdigit() or self.code[self.pos] == '.'):
                self.pos += 1
            num_str = self.code[start:self.pos]
            val = float(num_str) if '.' in num_str else int(num_str)
            return {"type": "Literal", "value": val}

        if char.isalpha() or char in "_$":
            return self._parse_identifier_or_keyword()

        self.pos += 1
        return {"type": "RawToken", "value": char}

def parse_program(self) -> Dict[str, Any]:
        body = []
        while self.pos < len(self.code):
            self._skip_whitespace()
            if self.pos >= len(self.code):
                break
            expr = self.parse_expression()
            if expr.get("type") != "Empty":
                body.append(expr)
        return {"type": "Program", "body": body}

class JSInterpreter:
    """Интерпретатор JavaScript для выполнения парсенного AST дерева"""
    def __init__(self, global_env: Optional[Environment] = None):
        self.global_env = global_env or Environment()
        self.event_loop = EventLoop()

    def evaluate(self, node: Dict[str, Any], env: Optional[Environment] = None) -> Any:
        if env is None:
            env = self.global_env

        node_type = node.get("type")

        if node_type == "Program":
            result = None
            for stmt in node.get("body", []):
                result = self.evaluate(stmt, env)
            return result

        elif node_type == "Literal":
            return node.get("value")

        elif node_type == "Identifier":
            name = node.get("name")
            return env.get(name)

        elif node_type == "Empty":
            return None

        return None

    def execute_script(self, code: str) -> Any:
        parser = _Parser(code)
        ast = parser.parse_program()
        return self.evaluate(ast)
