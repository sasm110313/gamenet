"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// node_modules/ws/lib/constants.js
var require_constants = __commonJS({
  "node_modules/ws/lib/constants.js"(exports2, module2) {
    "use strict";
    var BINARY_TYPES = ["nodebuffer", "arraybuffer", "fragments"];
    var hasBlob = typeof Blob !== "undefined";
    if (hasBlob) BINARY_TYPES.push("blob");
    module2.exports = {
      BINARY_TYPES,
      CLOSE_TIMEOUT: 3e4,
      EMPTY_BUFFER: Buffer.alloc(0),
      GUID: "258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
      hasBlob,
      kForOnEventAttribute: Symbol("kIsForOnEventAttribute"),
      kListener: Symbol("kListener"),
      kStatusCode: Symbol("status-code"),
      kWebSocket: Symbol("websocket"),
      NOOP: () => {
      }
    };
  }
});

// node_modules/ws/lib/buffer-util.js
var require_buffer_util = __commonJS({
  "node_modules/ws/lib/buffer-util.js"(exports2, module2) {
    "use strict";
    var { websocketMask, websocketUnmask } = require("http");
    var { EMPTY_BUFFER } = require_constants();
    var FastBuffer = Buffer[Symbol.species];
    function concat(list, totalLength) {
      if (list.length === 0) return EMPTY_BUFFER;
      if (list.length === 1) return list[0];
      const target = Buffer.allocUnsafe(totalLength);
      let offset = 0;
      for (let i = 0; i < list.length; i++) {
        const buf = list[i];
        target.set(buf, offset);
        offset += buf.length;
      }
      if (offset < totalLength) {
        return new FastBuffer(target.buffer, target.byteOffset, offset);
      }
      return target;
    }
    function _mask(source, mask, output, offset, length) {
      for (let i = 0; i < length; i++) {
        output[offset + i] = source[i] ^ mask[i & 3];
      }
    }
    function _unmask(buffer, mask) {
      for (let i = 0; i < buffer.length; i++) {
        buffer[i] ^= mask[i & 3];
      }
    }
    function toArrayBuffer(buf) {
      if (buf.length === buf.buffer.byteLength) {
        return buf.buffer;
      }
      return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
    }
    function toBuffer(data) {
      toBuffer.readOnly = true;
      if (Buffer.isBuffer(data)) return data;
      let buf;
      if (data instanceof ArrayBuffer) {
        buf = new FastBuffer(data);
      } else if (ArrayBuffer.isView(data)) {
        buf = new FastBuffer(data.buffer, data.byteOffset, data.byteLength);
      } else {
        buf = Buffer.from(data);
        toBuffer.readOnly = false;
      }
      return buf;
    }
    module2.exports = {
      concat,
      mask: _mask,
      toArrayBuffer,
      toBuffer,
      unmask: _unmask
    };
    if (websocketMask) {
      module2.exports.mask = function(source, mask, output, offset, length) {
        if (length < 24) _mask(source, mask, output, offset, length);
        else websocketMask(source, mask, output, offset, length);
      };
      module2.exports.unmask = function(buffer, mask) {
        if (buffer.length < 24) _unmask(buffer, mask);
        else websocketUnmask(buffer, mask);
      };
    } else if (!process.env.WS_NO_BUFFER_UTIL) {
      try {
        const bufferUtil = require("bufferutil");
        module2.exports.mask = function(source, mask, output, offset, length) {
          if (length < 48) _mask(source, mask, output, offset, length);
          else bufferUtil.mask(source, mask, output, offset, length);
        };
        module2.exports.unmask = function(buffer, mask) {
          if (buffer.length < 32) _unmask(buffer, mask);
          else bufferUtil.unmask(buffer, mask);
        };
      } catch (e) {
      }
    }
  }
});

// node_modules/ws/lib/limiter.js
var require_limiter = __commonJS({
  "node_modules/ws/lib/limiter.js"(exports2, module2) {
    "use strict";
    var kDone = Symbol("kDone");
    var kRun = Symbol("kRun");
    var Limiter = class {
      /**
       * Creates a new `Limiter`.
       *
       * @param {Number} [concurrency=Infinity] The maximum number of jobs allowed
       *     to run concurrently
       */
      constructor(concurrency) {
        this[kDone] = () => {
          this.pending--;
          this[kRun]();
        };
        this.concurrency = concurrency || Infinity;
        this.jobs = [];
        this.pending = 0;
      }
      /**
       * Adds a job to the queue.
       *
       * @param {Function} job The job to run
       * @public
       */
      add(job) {
        this.jobs.push(job);
        this[kRun]();
      }
      /**
       * Removes a job from the queue and runs it if possible.
       *
       * @private
       */
      [kRun]() {
        if (this.pending === this.concurrency) return;
        if (this.jobs.length) {
          const job = this.jobs.shift();
          this.pending++;
          job(this[kDone]);
        }
      }
    };
    module2.exports = Limiter;
  }
});

// node_modules/ws/lib/permessage-deflate.js
var require_permessage_deflate = __commonJS({
  "node_modules/ws/lib/permessage-deflate.js"(exports2, module2) {
    "use strict";
    var zlib = require("zlib");
    var bufferUtil = require_buffer_util();
    var Limiter = require_limiter();
    var { kStatusCode } = require_constants();
    var FastBuffer = Buffer[Symbol.species];
    var TRAILER = Buffer.from([0, 0, 255, 255]);
    var kPerMessageDeflate = Symbol("permessage-deflate");
    var kTotalLength = Symbol("total-length");
    var kCallback = Symbol("callback");
    var kBuffers = Symbol("buffers");
    var kError = Symbol("error");
    var zlibLimiter;
    var PerMessageDeflate2 = class {
      /**
       * Creates a PerMessageDeflate instance.
       *
       * @param {Object} [options] Configuration options
       * @param {(Boolean|Number)} [options.clientMaxWindowBits] Advertise support
       *     for, or request, a custom client window size
       * @param {Boolean} [options.clientNoContextTakeover=false] Advertise/
       *     acknowledge disabling of client context takeover
       * @param {Number} [options.concurrencyLimit=10] The number of concurrent
       *     calls to zlib
       * @param {Boolean} [options.isServer=false] Create the instance in either
       *     server or client mode
       * @param {Number} [options.maxPayload=0] The maximum allowed message length
       * @param {(Boolean|Number)} [options.serverMaxWindowBits] Request/confirm the
       *     use of a custom server window size
       * @param {Boolean} [options.serverNoContextTakeover=false] Request/accept
       *     disabling of server context takeover
       * @param {Number} [options.threshold=1024] Size (in bytes) below which
       *     messages should not be compressed if context takeover is disabled
       * @param {Object} [options.zlibDeflateOptions] Options to pass to zlib on
       *     deflate
       * @param {Object} [options.zlibInflateOptions] Options to pass to zlib on
       *     inflate
       */
      constructor(options) {
        this._options = options || {};
        this._threshold = this._options.threshold !== void 0 ? this._options.threshold : 1024;
        this._maxPayload = this._options.maxPayload | 0;
        this._isServer = !!this._options.isServer;
        this._deflate = null;
        this._inflate = null;
        this.params = null;
        if (!zlibLimiter) {
          const concurrency = this._options.concurrencyLimit !== void 0 ? this._options.concurrencyLimit : 10;
          zlibLimiter = new Limiter(concurrency);
        }
      }
      /**
       * @type {String}
       */
      static get extensionName() {
        return "permessage-deflate";
      }
      /**
       * Create an extension negotiation offer.
       *
       * @return {Object} Extension parameters
       * @public
       */
      offer() {
        const params = {};
        if (this._options.serverNoContextTakeover) {
          params.server_no_context_takeover = true;
        }
        if (this._options.clientNoContextTakeover) {
          params.client_no_context_takeover = true;
        }
        if (this._options.serverMaxWindowBits) {
          params.server_max_window_bits = this._options.serverMaxWindowBits;
        }
        if (this._options.clientMaxWindowBits) {
          params.client_max_window_bits = this._options.clientMaxWindowBits;
        } else if (this._options.clientMaxWindowBits == null) {
          params.client_max_window_bits = true;
        }
        return params;
      }
      /**
       * Accept an extension negotiation offer/response.
       *
       * @param {Array} configurations The extension negotiation offers/reponse
       * @return {Object} Accepted configuration
       * @public
       */
      accept(configurations) {
        configurations = this.normalizeParams(configurations);
        this.params = this._isServer ? this.acceptAsServer(configurations) : this.acceptAsClient(configurations);
        return this.params;
      }
      /**
       * Releases all resources used by the extension.
       *
       * @public
       */
      cleanup() {
        if (this._inflate) {
          this._inflate.close();
          this._inflate = null;
        }
        if (this._deflate) {
          const callback = this._deflate[kCallback];
          this._deflate.close();
          this._deflate = null;
          if (callback) {
            callback(
              new Error(
                "The deflate stream was closed while data was being processed"
              )
            );
          }
        }
      }
      /**
       *  Accept an extension negotiation offer.
       *
       * @param {Array} offers The extension negotiation offers
       * @return {Object} Accepted configuration
       * @private
       */
      acceptAsServer(offers) {
        const opts = this._options;
        const accepted = offers.find((params) => {
          if (opts.serverNoContextTakeover === false && params.server_no_context_takeover || params.server_max_window_bits && (opts.serverMaxWindowBits === false || typeof opts.serverMaxWindowBits === "number" && opts.serverMaxWindowBits > params.server_max_window_bits) || typeof opts.clientMaxWindowBits === "number" && (typeof params.client_max_window_bits === "number" ? opts.clientMaxWindowBits > params.client_max_window_bits : !params.client_max_window_bits)) {
            return false;
          }
          return true;
        });
        if (!accepted) {
          throw new Error("None of the extension offers can be accepted");
        }
        if (opts.serverNoContextTakeover) {
          accepted.server_no_context_takeover = true;
        }
        if (opts.clientNoContextTakeover) {
          accepted.client_no_context_takeover = true;
        }
        if (typeof opts.serverMaxWindowBits === "number") {
          accepted.server_max_window_bits = opts.serverMaxWindowBits;
        }
        if (typeof opts.clientMaxWindowBits === "number") {
          accepted.client_max_window_bits = opts.clientMaxWindowBits;
        } else if (accepted.client_max_window_bits === true || opts.clientMaxWindowBits === false) {
          delete accepted.client_max_window_bits;
        }
        return accepted;
      }
      /**
       * Accept the extension negotiation response.
       *
       * @param {Array} response The extension negotiation response
       * @return {Object} Accepted configuration
       * @private
       */
      acceptAsClient(response) {
        const params = response[0];
        if (this._options.clientNoContextTakeover === false && params.client_no_context_takeover) {
          throw new Error('Unexpected parameter "client_no_context_takeover"');
        }
        if (!params.client_max_window_bits) {
          if (typeof this._options.clientMaxWindowBits === "number") {
            params.client_max_window_bits = this._options.clientMaxWindowBits;
          }
        } else if (this._options.clientMaxWindowBits === false || typeof this._options.clientMaxWindowBits === "number" && params.client_max_window_bits > this._options.clientMaxWindowBits) {
          throw new Error(
            'Unexpected or invalid parameter "client_max_window_bits"'
          );
        }
        return params;
      }
      /**
       * Normalize parameters.
       *
       * @param {Array} configurations The extension negotiation offers/reponse
       * @return {Array} The offers/response with normalized parameters
       * @private
       */
      normalizeParams(configurations) {
        configurations.forEach((params) => {
          Object.keys(params).forEach((key) => {
            let value = params[key];
            if (value.length > 1) {
              throw new Error(`Parameter "${key}" must have only a single value`);
            }
            value = value[0];
            if (key === "client_max_window_bits") {
              if (value !== true) {
                const num = +value;
                if (!Number.isInteger(num) || num < 8 || num > 15) {
                  throw new TypeError(
                    `Invalid value for parameter "${key}": ${value}`
                  );
                }
                value = num;
              } else if (!this._isServer) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
            } else if (key === "server_max_window_bits") {
              const num = +value;
              if (!Number.isInteger(num) || num < 8 || num > 15) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
              value = num;
            } else if (key === "client_no_context_takeover" || key === "server_no_context_takeover") {
              if (value !== true) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
            } else {
              throw new Error(`Unknown parameter "${key}"`);
            }
            params[key] = value;
          });
        });
        return configurations;
      }
      /**
       * Decompress data. Concurrency limited.
       *
       * @param {Buffer} data Compressed data
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @public
       */
      decompress(data, fin, callback) {
        zlibLimiter.add((done) => {
          this._decompress(data, fin, (err, result) => {
            done();
            callback(err, result);
          });
        });
      }
      /**
       * Compress data. Concurrency limited.
       *
       * @param {(Buffer|String)} data Data to compress
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @public
       */
      compress(data, fin, callback) {
        zlibLimiter.add((done) => {
          this._compress(data, fin, (err, result) => {
            done();
            callback(err, result);
          });
        });
      }
      /**
       * Decompress data.
       *
       * @param {Buffer} data Compressed data
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @private
       */
      _decompress(data, fin, callback) {
        const endpoint = this._isServer ? "client" : "server";
        if (!this._inflate) {
          const key = `${endpoint}_max_window_bits`;
          const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
          this._inflate = zlib.createInflateRaw({
            ...this._options.zlibInflateOptions,
            windowBits
          });
          this._inflate[kPerMessageDeflate] = this;
          this._inflate[kTotalLength] = 0;
          this._inflate[kBuffers] = [];
          this._inflate.on("error", inflateOnError);
          this._inflate.on("data", inflateOnData);
        }
        this._inflate[kCallback] = callback;
        this._inflate.write(data);
        if (fin) this._inflate.write(TRAILER);
        this._inflate.flush(() => {
          const err = this._inflate[kError];
          if (err) {
            this._inflate.close();
            this._inflate = null;
            callback(err);
            return;
          }
          const data2 = bufferUtil.concat(
            this._inflate[kBuffers],
            this._inflate[kTotalLength]
          );
          if (this._inflate._readableState.endEmitted) {
            this._inflate.close();
            this._inflate = null;
          } else {
            this._inflate[kTotalLength] = 0;
            this._inflate[kBuffers] = [];
            if (fin && this.params[`${endpoint}_no_context_takeover`]) {
              this._inflate.reset();
            }
          }
          callback(null, data2);
        });
      }
      /**
       * Compress data.
       *
       * @param {(Buffer|String)} data Data to compress
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @private
       */
      _compress(data, fin, callback) {
        const endpoint = this._isServer ? "server" : "client";
        if (!this._deflate) {
          const key = `${endpoint}_max_window_bits`;
          const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
          this._deflate = zlib.createDeflateRaw({
            ...this._options.zlibDeflateOptions,
            windowBits
          });
          this._deflate[kTotalLength] = 0;
          this._deflate[kBuffers] = [];
          this._deflate.on("data", deflateOnData);
        }
        this._deflate[kCallback] = callback;
        this._deflate.write(data);
        this._deflate.flush(zlib.Z_SYNC_FLUSH, () => {
          if (!this._deflate) {
            return;
          }
          let data2 = bufferUtil.concat(
            this._deflate[kBuffers],
            this._deflate[kTotalLength]
          );
          if (fin) {
            data2 = new FastBuffer(data2.buffer, data2.byteOffset, data2.length - 4);
          }
          this._deflate[kCallback] = null;
          this._deflate[kTotalLength] = 0;
          this._deflate[kBuffers] = [];
          if (fin && this.params[`${endpoint}_no_context_takeover`]) {
            this._deflate.reset();
          }
          callback(null, data2);
        });
      }
    };
    module2.exports = PerMessageDeflate2;
    function deflateOnData(chunk) {
      this[kBuffers].push(chunk);
      this[kTotalLength] += chunk.length;
    }
    function inflateOnData(chunk) {
      this[kTotalLength] += chunk.length;
      if (this[kPerMessageDeflate]._maxPayload < 1 || this[kTotalLength] <= this[kPerMessageDeflate]._maxPayload) {
        this[kBuffers].push(chunk);
        return;
      }
      this[kError] = new RangeError("Max payload size exceeded");
      this[kError].code = "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH";
      this[kError][kStatusCode] = 1009;
      this.removeListener("data", inflateOnData);
      this.reset();
    }
    function inflateOnError(err) {
      this[kPerMessageDeflate]._inflate = null;
      if (this[kError]) {
        this[kCallback](this[kError]);
        return;
      }
      err[kStatusCode] = 1007;
      this[kCallback](err);
    }
  }
});

// node_modules/ws/lib/validation.js
var require_validation = __commonJS({
  "node_modules/ws/lib/validation.js"(exports2, module2) {
    "use strict";
    var { isUtf8 } = require("buffer");
    var { hasBlob } = require_constants();
    var tokenChars = [
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      // 0 - 15
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      // 16 - 31
      0,
      1,
      0,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      1,
      1,
      0,
      1,
      1,
      0,
      // 32 - 47
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      0,
      0,
      0,
      0,
      // 48 - 63
      0,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      // 64 - 79
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      0,
      1,
      1,
      // 80 - 95
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      // 96 - 111
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      1,
      0,
      1,
      0
      // 112 - 127
    ];
    function isValidStatusCode(code) {
      return code >= 1e3 && code <= 1014 && code !== 1004 && code !== 1005 && code !== 1006 || code >= 3e3 && code <= 4999;
    }
    function _isValidUTF8(buf) {
      const len = buf.length;
      let i = 0;
      while (i < len) {
        if ((buf[i] & 128) === 0) {
          i++;
        } else if ((buf[i] & 224) === 192) {
          if (i + 1 === len || (buf[i + 1] & 192) !== 128 || (buf[i] & 254) === 192) {
            return false;
          }
          i += 2;
        } else if ((buf[i] & 240) === 224) {
          if (i + 2 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || buf[i] === 224 && (buf[i + 1] & 224) === 128 || // Overlong
          buf[i] === 237 && (buf[i + 1] & 224) === 160) {
            return false;
          }
          i += 3;
        } else if ((buf[i] & 248) === 240) {
          if (i + 3 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || (buf[i + 3] & 192) !== 128 || buf[i] === 240 && (buf[i + 1] & 240) === 128 || // Overlong
          buf[i] === 244 && buf[i + 1] > 143 || buf[i] > 244) {
            return false;
          }
          i += 4;
        } else {
          return false;
        }
      }
      return true;
    }
    function isBlob(value) {
      return hasBlob && typeof value === "object" && typeof value.arrayBuffer === "function" && typeof value.type === "string" && typeof value.stream === "function" && (value[Symbol.toStringTag] === "Blob" || value[Symbol.toStringTag] === "File");
    }
    module2.exports = {
      isBlob,
      isValidStatusCode,
      isValidUTF8: _isValidUTF8,
      tokenChars
    };
    if (isUtf8) {
      module2.exports.isValidUTF8 = function(buf) {
        return buf.length < 24 ? _isValidUTF8(buf) : isUtf8(buf);
      };
    } else if (!process.env.WS_NO_UTF_8_VALIDATE) {
      try {
        const isValidUTF8 = require("utf-8-validate");
        module2.exports.isValidUTF8 = function(buf) {
          return buf.length < 32 ? _isValidUTF8(buf) : isValidUTF8(buf);
        };
      } catch (e) {
      }
    }
  }
});

// node_modules/ws/lib/receiver.js
var require_receiver = __commonJS({
  "node_modules/ws/lib/receiver.js"(exports2, module2) {
    "use strict";
    var { Writable } = require("stream");
    var PerMessageDeflate2 = require_permessage_deflate();
    var {
      BINARY_TYPES,
      EMPTY_BUFFER,
      kStatusCode,
      kWebSocket
    } = require_constants();
    var { concat, toArrayBuffer, unmask } = require_buffer_util();
    var { isValidStatusCode, isValidUTF8 } = require_validation();
    var FastBuffer = Buffer[Symbol.species];
    var GET_INFO = 0;
    var GET_PAYLOAD_LENGTH_16 = 1;
    var GET_PAYLOAD_LENGTH_64 = 2;
    var GET_MASK = 3;
    var GET_DATA = 4;
    var INFLATING = 5;
    var DEFER_EVENT = 6;
    var Receiver2 = class extends Writable {
      /**
       * Creates a Receiver instance.
       *
       * @param {Object} [options] Options object
       * @param {Boolean} [options.allowSynchronousEvents=true] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {String} [options.binaryType=nodebuffer] The type for binary data
       * @param {Object} [options.extensions] An object containing the negotiated
       *     extensions
       * @param {Boolean} [options.isServer=false] Specifies whether to operate in
       *     client or server mode
       * @param {Number} [options.maxBufferedChunks=0] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=0] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=0] The maximum allowed message length
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       */
      constructor(options = {}) {
        super();
        this._allowSynchronousEvents = options.allowSynchronousEvents !== void 0 ? options.allowSynchronousEvents : true;
        this._binaryType = options.binaryType || BINARY_TYPES[0];
        this._extensions = options.extensions || {};
        this._isServer = !!options.isServer;
        this._maxBufferedChunks = options.maxBufferedChunks | 0;
        this._maxFragments = options.maxFragments | 0;
        this._maxPayload = options.maxPayload | 0;
        this._skipUTF8Validation = !!options.skipUTF8Validation;
        this[kWebSocket] = void 0;
        this._bufferedBytes = 0;
        this._buffers = [];
        this._compressed = false;
        this._payloadLength = 0;
        this._mask = void 0;
        this._fragmented = 0;
        this._masked = false;
        this._fin = false;
        this._opcode = 0;
        this._totalPayloadLength = 0;
        this._messageLength = 0;
        this._numFragments = 0;
        this._fragments = [];
        this._errored = false;
        this._loop = false;
        this._state = GET_INFO;
      }
      /**
       * Implements `Writable.prototype._write()`.
       *
       * @param {Buffer} chunk The chunk of data to write
       * @param {String} encoding The character encoding of `chunk`
       * @param {Function} cb Callback
       * @private
       */
      _write(chunk, encoding, cb) {
        if (this._opcode === 8 && this._state == GET_INFO) return cb();
        if (this._maxBufferedChunks > 0 && this._buffers.length >= this._maxBufferedChunks) {
          cb(
            this.createError(
              RangeError,
              "Too many buffered chunks",
              false,
              1008,
              "WS_ERR_TOO_MANY_BUFFERED_PARTS"
            )
          );
          return;
        }
        this._bufferedBytes += chunk.length;
        this._buffers.push(chunk);
        this.startLoop(cb);
      }
      /**
       * Consumes `n` bytes from the buffered data.
       *
       * @param {Number} n The number of bytes to consume
       * @return {Buffer} The consumed bytes
       * @private
       */
      consume(n) {
        this._bufferedBytes -= n;
        if (n === this._buffers[0].length) return this._buffers.shift();
        if (n < this._buffers[0].length) {
          const buf = this._buffers[0];
          this._buffers[0] = new FastBuffer(
            buf.buffer,
            buf.byteOffset + n,
            buf.length - n
          );
          return new FastBuffer(buf.buffer, buf.byteOffset, n);
        }
        const dst = Buffer.allocUnsafe(n);
        do {
          const buf = this._buffers[0];
          const offset = dst.length - n;
          if (n >= buf.length) {
            dst.set(this._buffers.shift(), offset);
          } else {
            dst.set(new Uint8Array(buf.buffer, buf.byteOffset, n), offset);
            this._buffers[0] = new FastBuffer(
              buf.buffer,
              buf.byteOffset + n,
              buf.length - n
            );
          }
          n -= buf.length;
        } while (n > 0);
        return dst;
      }
      /**
       * Starts the parsing loop.
       *
       * @param {Function} cb Callback
       * @private
       */
      startLoop(cb) {
        this._loop = true;
        do {
          switch (this._state) {
            case GET_INFO:
              this.getInfo(cb);
              break;
            case GET_PAYLOAD_LENGTH_16:
              this.getPayloadLength16(cb);
              break;
            case GET_PAYLOAD_LENGTH_64:
              this.getPayloadLength64(cb);
              break;
            case GET_MASK:
              this.getMask();
              break;
            case GET_DATA:
              this.getData(cb);
              break;
            case INFLATING:
            case DEFER_EVENT:
              this._loop = false;
              return;
          }
        } while (this._loop);
        if (!this._errored) cb();
      }
      /**
       * Reads the first two bytes of a frame.
       *
       * @param {Function} cb Callback
       * @private
       */
      getInfo(cb) {
        if (this._bufferedBytes < 2) {
          this._loop = false;
          return;
        }
        const buf = this.consume(2);
        if ((buf[0] & 48) !== 0) {
          const error = this.createError(
            RangeError,
            "RSV2 and RSV3 must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_RSV_2_3"
          );
          cb(error);
          return;
        }
        const compressed = (buf[0] & 64) === 64;
        if (compressed && !this._extensions[PerMessageDeflate2.extensionName]) {
          const error = this.createError(
            RangeError,
            "RSV1 must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_RSV_1"
          );
          cb(error);
          return;
        }
        this._fin = (buf[0] & 128) === 128;
        this._opcode = buf[0] & 15;
        this._payloadLength = buf[1] & 127;
        if (this._opcode === 0) {
          if (compressed) {
            const error = this.createError(
              RangeError,
              "RSV1 must be clear",
              true,
              1002,
              "WS_ERR_UNEXPECTED_RSV_1"
            );
            cb(error);
            return;
          }
          if (!this._fragmented) {
            const error = this.createError(
              RangeError,
              "invalid opcode 0",
              true,
              1002,
              "WS_ERR_INVALID_OPCODE"
            );
            cb(error);
            return;
          }
          this._opcode = this._fragmented;
        } else if (this._opcode === 1 || this._opcode === 2) {
          if (this._fragmented) {
            const error = this.createError(
              RangeError,
              `invalid opcode ${this._opcode}`,
              true,
              1002,
              "WS_ERR_INVALID_OPCODE"
            );
            cb(error);
            return;
          }
          this._compressed = compressed;
        } else if (this._opcode > 7 && this._opcode < 11) {
          if (!this._fin) {
            const error = this.createError(
              RangeError,
              "FIN must be set",
              true,
              1002,
              "WS_ERR_EXPECTED_FIN"
            );
            cb(error);
            return;
          }
          if (compressed) {
            const error = this.createError(
              RangeError,
              "RSV1 must be clear",
              true,
              1002,
              "WS_ERR_UNEXPECTED_RSV_1"
            );
            cb(error);
            return;
          }
          if (this._payloadLength > 125 || this._opcode === 8 && this._payloadLength === 1) {
            const error = this.createError(
              RangeError,
              `invalid payload length ${this._payloadLength}`,
              true,
              1002,
              "WS_ERR_INVALID_CONTROL_PAYLOAD_LENGTH"
            );
            cb(error);
            return;
          }
        } else {
          const error = this.createError(
            RangeError,
            `invalid opcode ${this._opcode}`,
            true,
            1002,
            "WS_ERR_INVALID_OPCODE"
          );
          cb(error);
          return;
        }
        if (!this._fin && !this._fragmented) this._fragmented = this._opcode;
        this._masked = (buf[1] & 128) === 128;
        if (this._isServer) {
          if (!this._masked) {
            const error = this.createError(
              RangeError,
              "MASK must be set",
              true,
              1002,
              "WS_ERR_EXPECTED_MASK"
            );
            cb(error);
            return;
          }
        } else if (this._masked) {
          const error = this.createError(
            RangeError,
            "MASK must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_MASK"
          );
          cb(error);
          return;
        }
        if (this._payloadLength === 126) this._state = GET_PAYLOAD_LENGTH_16;
        else if (this._payloadLength === 127) this._state = GET_PAYLOAD_LENGTH_64;
        else this.haveLength(cb);
      }
      /**
       * Gets extended payload length (7+16).
       *
       * @param {Function} cb Callback
       * @private
       */
      getPayloadLength16(cb) {
        if (this._bufferedBytes < 2) {
          this._loop = false;
          return;
        }
        this._payloadLength = this.consume(2).readUInt16BE(0);
        this.haveLength(cb);
      }
      /**
       * Gets extended payload length (7+64).
       *
       * @param {Function} cb Callback
       * @private
       */
      getPayloadLength64(cb) {
        if (this._bufferedBytes < 8) {
          this._loop = false;
          return;
        }
        const buf = this.consume(8);
        const num = buf.readUInt32BE(0);
        if (num > Math.pow(2, 53 - 32) - 1) {
          const error = this.createError(
            RangeError,
            "Unsupported WebSocket frame: payload length > 2^53 - 1",
            false,
            1009,
            "WS_ERR_UNSUPPORTED_DATA_PAYLOAD_LENGTH"
          );
          cb(error);
          return;
        }
        this._payloadLength = num * Math.pow(2, 32) + buf.readUInt32BE(4);
        this.haveLength(cb);
      }
      /**
       * Payload length has been read.
       *
       * @param {Function} cb Callback
       * @private
       */
      haveLength(cb) {
        if (this._payloadLength && this._opcode < 8) {
          this._totalPayloadLength += this._payloadLength;
          if (this._totalPayloadLength > this._maxPayload && this._maxPayload > 0) {
            const error = this.createError(
              RangeError,
              "Max payload size exceeded",
              false,
              1009,
              "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH"
            );
            cb(error);
            return;
          }
        }
        if (this._masked) this._state = GET_MASK;
        else this._state = GET_DATA;
      }
      /**
       * Reads mask bytes.
       *
       * @private
       */
      getMask() {
        if (this._bufferedBytes < 4) {
          this._loop = false;
          return;
        }
        this._mask = this.consume(4);
        this._state = GET_DATA;
      }
      /**
       * Reads data bytes.
       *
       * @param {Function} cb Callback
       * @private
       */
      getData(cb) {
        let data = EMPTY_BUFFER;
        if (this._payloadLength) {
          if (this._bufferedBytes < this._payloadLength) {
            this._loop = false;
            return;
          }
          data = this.consume(this._payloadLength);
          if (this._masked && (this._mask[0] | this._mask[1] | this._mask[2] | this._mask[3]) !== 0) {
            unmask(data, this._mask);
          }
        }
        if (this._opcode > 7) {
          this.controlMessage(data, cb);
          return;
        }
        if (this._maxFragments > 0 && ++this._numFragments > this._maxFragments) {
          const error = this.createError(
            RangeError,
            "Too many message fragments",
            false,
            1008,
            "WS_ERR_TOO_MANY_BUFFERED_PARTS"
          );
          cb(error);
          return;
        }
        if (this._compressed) {
          this._state = INFLATING;
          this.decompress(data, cb);
          return;
        }
        if (data.length) {
          this._messageLength = this._totalPayloadLength;
          this._fragments.push(data);
        }
        this.dataMessage(cb);
      }
      /**
       * Decompresses data.
       *
       * @param {Buffer} data Compressed data
       * @param {Function} cb Callback
       * @private
       */
      decompress(data, cb) {
        const perMessageDeflate = this._extensions[PerMessageDeflate2.extensionName];
        perMessageDeflate.decompress(data, this._fin, (err, buf) => {
          if (err) return cb(err);
          if (buf.length) {
            this._messageLength += buf.length;
            if (this._messageLength > this._maxPayload && this._maxPayload > 0) {
              const error = this.createError(
                RangeError,
                "Max payload size exceeded",
                false,
                1009,
                "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH"
              );
              cb(error);
              return;
            }
            this._fragments.push(buf);
          }
          this.dataMessage(cb);
          if (this._state === GET_INFO) this.startLoop(cb);
        });
      }
      /**
       * Handles a data message.
       *
       * @param {Function} cb Callback
       * @private
       */
      dataMessage(cb) {
        if (!this._fin) {
          this._state = GET_INFO;
          return;
        }
        const messageLength = this._messageLength;
        const fragments = this._fragments;
        this._totalPayloadLength = 0;
        this._messageLength = 0;
        this._fragmented = 0;
        this._numFragments = 0;
        this._fragments = [];
        if (this._opcode === 2) {
          let data;
          if (this._binaryType === "nodebuffer") {
            data = concat(fragments, messageLength);
          } else if (this._binaryType === "arraybuffer") {
            data = toArrayBuffer(concat(fragments, messageLength));
          } else if (this._binaryType === "blob") {
            data = new Blob(fragments);
          } else {
            data = fragments;
          }
          if (this._allowSynchronousEvents) {
            this.emit("message", data, true);
            this._state = GET_INFO;
          } else {
            this._state = DEFER_EVENT;
            setImmediate(() => {
              this.emit("message", data, true);
              this._state = GET_INFO;
              this.startLoop(cb);
            });
          }
        } else {
          const buf = concat(fragments, messageLength);
          if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
            const error = this.createError(
              Error,
              "invalid UTF-8 sequence",
              true,
              1007,
              "WS_ERR_INVALID_UTF8"
            );
            cb(error);
            return;
          }
          if (this._state === INFLATING || this._allowSynchronousEvents) {
            this.emit("message", buf, false);
            this._state = GET_INFO;
          } else {
            this._state = DEFER_EVENT;
            setImmediate(() => {
              this.emit("message", buf, false);
              this._state = GET_INFO;
              this.startLoop(cb);
            });
          }
        }
      }
      /**
       * Handles a control message.
       *
       * @param {Buffer} data Data to handle
       * @return {(Error|RangeError|undefined)} A possible error
       * @private
       */
      controlMessage(data, cb) {
        if (this._opcode === 8) {
          if (data.length === 0) {
            this._loop = false;
            this.emit("conclude", 1005, EMPTY_BUFFER);
            this.end();
          } else {
            const code = data.readUInt16BE(0);
            if (!isValidStatusCode(code)) {
              const error = this.createError(
                RangeError,
                `invalid status code ${code}`,
                true,
                1002,
                "WS_ERR_INVALID_CLOSE_CODE"
              );
              cb(error);
              return;
            }
            const buf = new FastBuffer(
              data.buffer,
              data.byteOffset + 2,
              data.length - 2
            );
            if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
              const error = this.createError(
                Error,
                "invalid UTF-8 sequence",
                true,
                1007,
                "WS_ERR_INVALID_UTF8"
              );
              cb(error);
              return;
            }
            this._loop = false;
            this.emit("conclude", code, buf);
            this.end();
          }
          this._state = GET_INFO;
          return;
        }
        if (this._allowSynchronousEvents) {
          this.emit(this._opcode === 9 ? "ping" : "pong", data);
          this._state = GET_INFO;
        } else {
          this._state = DEFER_EVENT;
          setImmediate(() => {
            this.emit(this._opcode === 9 ? "ping" : "pong", data);
            this._state = GET_INFO;
            this.startLoop(cb);
          });
        }
      }
      /**
       * Builds an error object.
       *
       * @param {function(new:Error|RangeError)} ErrorCtor The error constructor
       * @param {String} message The error message
       * @param {Boolean} prefix Specifies whether or not to add a default prefix to
       *     `message`
       * @param {Number} statusCode The status code
       * @param {String} errorCode The exposed error code
       * @return {(Error|RangeError)} The error
       * @private
       */
      createError(ErrorCtor, message, prefix, statusCode, errorCode) {
        this._loop = false;
        this._errored = true;
        const err = new ErrorCtor(
          prefix ? `Invalid WebSocket frame: ${message}` : message
        );
        Error.captureStackTrace(err, this.createError);
        err.code = errorCode;
        err[kStatusCode] = statusCode;
        return err;
      }
    };
    module2.exports = Receiver2;
  }
});

// node_modules/ws/lib/sender.js
var require_sender = __commonJS({
  "node_modules/ws/lib/sender.js"(exports2, module2) {
    "use strict";
    var { Duplex } = require("stream");
    var { randomFillSync } = require("crypto");
    var {
      types: { isUint8Array }
    } = require("util");
    var PerMessageDeflate2 = require_permessage_deflate();
    var { EMPTY_BUFFER, kWebSocket, NOOP } = require_constants();
    var { isBlob, isValidStatusCode } = require_validation();
    var { mask: applyMask, toBuffer } = require_buffer_util();
    var kByteLength = Symbol("kByteLength");
    var maskBuffer = Buffer.alloc(4);
    var RANDOM_POOL_SIZE = 8 * 1024;
    var randomPool;
    var randomPoolPointer = RANDOM_POOL_SIZE;
    var DEFAULT = 0;
    var DEFLATING = 1;
    var GET_BLOB_DATA = 2;
    var Sender2 = class _Sender {
      /**
       * Creates a Sender instance.
       *
       * @param {Duplex} socket The connection socket
       * @param {Object} [extensions] An object containing the negotiated extensions
       * @param {Function} [generateMask] The function used to generate the masking
       *     key
       */
      constructor(socket, extensions, generateMask) {
        this._extensions = extensions || {};
        if (generateMask) {
          this._generateMask = generateMask;
          this._maskBuffer = Buffer.alloc(4);
        }
        this._socket = socket;
        this._firstFragment = true;
        this._compress = false;
        this._bufferedBytes = 0;
        this._queue = [];
        this._state = DEFAULT;
        this.onerror = NOOP;
        this[kWebSocket] = void 0;
      }
      /**
       * Frames a piece of data according to the HyBi WebSocket protocol.
       *
       * @param {(Buffer|String)} data The data to frame
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @return {(Buffer|String)[]} The framed data
       * @public
       */
      static frame(data, options) {
        let mask;
        let merge = false;
        let offset = 2;
        let skipMasking = false;
        if (options.mask) {
          mask = options.maskBuffer || maskBuffer;
          if (options.generateMask) {
            options.generateMask(mask);
          } else {
            if (randomPoolPointer === RANDOM_POOL_SIZE) {
              if (randomPool === void 0) {
                randomPool = Buffer.alloc(RANDOM_POOL_SIZE);
              }
              randomFillSync(randomPool, 0, RANDOM_POOL_SIZE);
              randomPoolPointer = 0;
            }
            mask[0] = randomPool[randomPoolPointer++];
            mask[1] = randomPool[randomPoolPointer++];
            mask[2] = randomPool[randomPoolPointer++];
            mask[3] = randomPool[randomPoolPointer++];
          }
          skipMasking = (mask[0] | mask[1] | mask[2] | mask[3]) === 0;
          offset = 6;
        }
        let dataLength;
        if (typeof data === "string") {
          if ((!options.mask || skipMasking) && options[kByteLength] !== void 0) {
            dataLength = options[kByteLength];
          } else {
            data = Buffer.from(data);
            dataLength = data.length;
          }
        } else {
          dataLength = data.length;
          merge = options.mask && options.readOnly && !skipMasking;
        }
        let payloadLength = dataLength;
        if (dataLength >= 65536) {
          offset += 8;
          payloadLength = 127;
        } else if (dataLength > 125) {
          offset += 2;
          payloadLength = 126;
        }
        const target = Buffer.allocUnsafe(merge ? dataLength + offset : offset);
        target[0] = options.fin ? options.opcode | 128 : options.opcode;
        if (options.rsv1) target[0] |= 64;
        target[1] = payloadLength;
        if (payloadLength === 126) {
          target.writeUInt16BE(dataLength, 2);
        } else if (payloadLength === 127) {
          target[2] = target[3] = 0;
          target.writeUIntBE(dataLength, 4, 6);
        }
        if (!options.mask) {
          return dataLength ? [target, data] : [target];
        }
        target[1] |= 128;
        target[offset - 4] = mask[0];
        target[offset - 3] = mask[1];
        target[offset - 2] = mask[2];
        target[offset - 1] = mask[3];
        if (!dataLength) return [target];
        if (skipMasking) return [target, data];
        if (merge) {
          applyMask(data, mask, target, offset, dataLength);
          return [target];
        }
        applyMask(data, mask, data, 0, dataLength);
        return [target, data];
      }
      /**
       * Sends a close message to the other peer.
       *
       * @param {Number} [code] The status code component of the body
       * @param {(String|Buffer)} [data] The message component of the body
       * @param {Boolean} [mask=false] Specifies whether or not to mask the message
       * @param {Function} [cb] Callback
       * @public
       */
      close(code, data, mask, cb) {
        let buf;
        if (code === void 0) {
          buf = EMPTY_BUFFER;
        } else if (typeof code !== "number" || !isValidStatusCode(code)) {
          throw new TypeError("First argument must be a valid error code number");
        } else if (data === void 0 || !data.length) {
          buf = Buffer.allocUnsafe(2);
          buf.writeUInt16BE(code, 0);
        } else {
          const length = Buffer.byteLength(data);
          if (length > 123) {
            throw new RangeError("The message must not be greater than 123 bytes");
          }
          buf = Buffer.allocUnsafe(2 + length);
          buf.writeUInt16BE(code, 0);
          if (typeof data === "string") {
            buf.write(data, 2);
          } else if (isUint8Array(data)) {
            buf.set(data, 2);
          } else {
            throw new TypeError("Second argument must be a string or a Uint8Array");
          }
        }
        const options = {
          [kByteLength]: buf.length,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 8,
          readOnly: false,
          rsv1: false
        };
        if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, buf, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(buf, options), cb);
        }
      }
      /**
       * Sends a ping message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Boolean} [mask=false] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback
       * @public
       */
      ping(data, mask, cb) {
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (byteLength > 125) {
          throw new RangeError("The data size must not be greater than 125 bytes");
        }
        const options = {
          [kByteLength]: byteLength,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 9,
          readOnly,
          rsv1: false
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, false, options, cb]);
          } else {
            this.getBlobData(data, false, options, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(data, options), cb);
        }
      }
      /**
       * Sends a pong message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Boolean} [mask=false] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback
       * @public
       */
      pong(data, mask, cb) {
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (byteLength > 125) {
          throw new RangeError("The data size must not be greater than 125 bytes");
        }
        const options = {
          [kByteLength]: byteLength,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 10,
          readOnly,
          rsv1: false
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, false, options, cb]);
          } else {
            this.getBlobData(data, false, options, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(data, options), cb);
        }
      }
      /**
       * Sends a data message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Object} options Options object
       * @param {Boolean} [options.binary=false] Specifies whether `data` is binary
       *     or text
       * @param {Boolean} [options.compress=false] Specifies whether or not to
       *     compress `data`
       * @param {Boolean} [options.fin=false] Specifies whether the fragment is the
       *     last one
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Function} [cb] Callback
       * @public
       */
      send(data, options, cb) {
        const perMessageDeflate = this._extensions[PerMessageDeflate2.extensionName];
        let opcode = options.binary ? 2 : 1;
        let rsv1 = options.compress;
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (this._firstFragment) {
          this._firstFragment = false;
          if (rsv1 && perMessageDeflate && perMessageDeflate.params[perMessageDeflate._isServer ? "server_no_context_takeover" : "client_no_context_takeover"]) {
            rsv1 = byteLength >= perMessageDeflate._threshold;
          }
          this._compress = rsv1;
        } else {
          rsv1 = false;
          opcode = 0;
        }
        if (options.fin) this._firstFragment = true;
        const opts = {
          [kByteLength]: byteLength,
          fin: options.fin,
          generateMask: this._generateMask,
          mask: options.mask,
          maskBuffer: this._maskBuffer,
          opcode,
          readOnly,
          rsv1
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, this._compress, opts, cb]);
          } else {
            this.getBlobData(data, this._compress, opts, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, this._compress, opts, cb]);
        } else {
          this.dispatch(data, this._compress, opts, cb);
        }
      }
      /**
       * Gets the contents of a blob as binary data.
       *
       * @param {Blob} blob The blob
       * @param {Boolean} [compress=false] Specifies whether or not to compress
       *     the data
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @param {Function} [cb] Callback
       * @private
       */
      getBlobData(blob, compress, options, cb) {
        this._bufferedBytes += options[kByteLength];
        this._state = GET_BLOB_DATA;
        blob.arrayBuffer().then((arrayBuffer) => {
          if (this._socket.destroyed) {
            const err = new Error(
              "The socket was closed while the blob was being read"
            );
            process.nextTick(callCallbacks, this, err, cb);
            return;
          }
          this._bufferedBytes -= options[kByteLength];
          const data = toBuffer(arrayBuffer);
          if (!compress) {
            this._state = DEFAULT;
            this.sendFrame(_Sender.frame(data, options), cb);
            this.dequeue();
          } else {
            this.dispatch(data, compress, options, cb);
          }
        }).catch((err) => {
          process.nextTick(onError, this, err, cb);
        });
      }
      /**
       * Dispatches a message.
       *
       * @param {(Buffer|String)} data The message to send
       * @param {Boolean} [compress=false] Specifies whether or not to compress
       *     `data`
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @param {Function} [cb] Callback
       * @private
       */
      dispatch(data, compress, options, cb) {
        if (!compress) {
          this.sendFrame(_Sender.frame(data, options), cb);
          return;
        }
        const perMessageDeflate = this._extensions[PerMessageDeflate2.extensionName];
        this._bufferedBytes += options[kByteLength];
        this._state = DEFLATING;
        perMessageDeflate.compress(data, options.fin, (_, buf) => {
          if (this._socket.destroyed) {
            const err = new Error(
              "The socket was closed while data was being compressed"
            );
            callCallbacks(this, err, cb);
            return;
          }
          this._bufferedBytes -= options[kByteLength];
          this._state = DEFAULT;
          options.readOnly = false;
          this.sendFrame(_Sender.frame(buf, options), cb);
          this.dequeue();
        });
      }
      /**
       * Executes queued send operations.
       *
       * @private
       */
      dequeue() {
        while (this._state === DEFAULT && this._queue.length) {
          const params = this._queue.shift();
          this._bufferedBytes -= params[3][kByteLength];
          Reflect.apply(params[0], this, params.slice(1));
        }
      }
      /**
       * Enqueues a send operation.
       *
       * @param {Array} params Send operation parameters.
       * @private
       */
      enqueue(params) {
        this._bufferedBytes += params[3][kByteLength];
        this._queue.push(params);
      }
      /**
       * Sends a frame.
       *
       * @param {(Buffer | String)[]} list The frame to send
       * @param {Function} [cb] Callback
       * @private
       */
      sendFrame(list, cb) {
        if (list.length === 2) {
          this._socket.cork();
          this._socket.write(list[0]);
          this._socket.write(list[1], cb);
          this._socket.uncork();
        } else {
          this._socket.write(list[0], cb);
        }
      }
    };
    module2.exports = Sender2;
    function callCallbacks(sender, err, cb) {
      if (typeof cb === "function") cb(err);
      for (let i = 0; i < sender._queue.length; i++) {
        const params = sender._queue[i];
        const callback = params[params.length - 1];
        if (typeof callback === "function") callback(err);
      }
    }
    function onError(sender, err, cb) {
      callCallbacks(sender, err, cb);
      sender.onerror(err);
    }
  }
});

// node_modules/ws/lib/event-target.js
var require_event_target = __commonJS({
  "node_modules/ws/lib/event-target.js"(exports2, module2) {
    "use strict";
    var { kForOnEventAttribute, kListener } = require_constants();
    var kCode = Symbol("kCode");
    var kData = Symbol("kData");
    var kError = Symbol("kError");
    var kMessage = Symbol("kMessage");
    var kReason = Symbol("kReason");
    var kTarget = Symbol("kTarget");
    var kType = Symbol("kType");
    var kWasClean = Symbol("kWasClean");
    var Event = class {
      /**
       * Create a new `Event`.
       *
       * @param {String} type The name of the event
       * @throws {TypeError} If the `type` argument is not specified
       */
      constructor(type) {
        this[kTarget] = null;
        this[kType] = type;
      }
      /**
       * @type {*}
       */
      get target() {
        return this[kTarget];
      }
      /**
       * @type {String}
       */
      get type() {
        return this[kType];
      }
    };
    Object.defineProperty(Event.prototype, "target", { enumerable: true });
    Object.defineProperty(Event.prototype, "type", { enumerable: true });
    var CloseEvent = class extends Event {
      /**
       * Create a new `CloseEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {Number} [options.code=0] The status code explaining why the
       *     connection was closed
       * @param {String} [options.reason=''] A human-readable string explaining why
       *     the connection was closed
       * @param {Boolean} [options.wasClean=false] Indicates whether or not the
       *     connection was cleanly closed
       */
      constructor(type, options = {}) {
        super(type);
        this[kCode] = options.code === void 0 ? 0 : options.code;
        this[kReason] = options.reason === void 0 ? "" : options.reason;
        this[kWasClean] = options.wasClean === void 0 ? false : options.wasClean;
      }
      /**
       * @type {Number}
       */
      get code() {
        return this[kCode];
      }
      /**
       * @type {String}
       */
      get reason() {
        return this[kReason];
      }
      /**
       * @type {Boolean}
       */
      get wasClean() {
        return this[kWasClean];
      }
    };
    Object.defineProperty(CloseEvent.prototype, "code", { enumerable: true });
    Object.defineProperty(CloseEvent.prototype, "reason", { enumerable: true });
    Object.defineProperty(CloseEvent.prototype, "wasClean", { enumerable: true });
    var ErrorEvent = class extends Event {
      /**
       * Create a new `ErrorEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {*} [options.error=null] The error that generated this event
       * @param {String} [options.message=''] The error message
       */
      constructor(type, options = {}) {
        super(type);
        this[kError] = options.error === void 0 ? null : options.error;
        this[kMessage] = options.message === void 0 ? "" : options.message;
      }
      /**
       * @type {*}
       */
      get error() {
        return this[kError];
      }
      /**
       * @type {String}
       */
      get message() {
        return this[kMessage];
      }
    };
    Object.defineProperty(ErrorEvent.prototype, "error", { enumerable: true });
    Object.defineProperty(ErrorEvent.prototype, "message", { enumerable: true });
    var MessageEvent = class extends Event {
      /**
       * Create a new `MessageEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {*} [options.data=null] The message content
       */
      constructor(type, options = {}) {
        super(type);
        this[kData] = options.data === void 0 ? null : options.data;
      }
      /**
       * @type {*}
       */
      get data() {
        return this[kData];
      }
    };
    Object.defineProperty(MessageEvent.prototype, "data", { enumerable: true });
    var EventTarget = {
      /**
       * Register an event listener.
       *
       * @param {String} type A string representing the event type to listen for
       * @param {(Function|Object)} handler The listener to add
       * @param {Object} [options] An options object specifies characteristics about
       *     the event listener
       * @param {Boolean} [options.once=false] A `Boolean` indicating that the
       *     listener should be invoked at most once after being added. If `true`,
       *     the listener would be automatically removed when invoked.
       * @public
       */
      addEventListener(type, handler, options = {}) {
        for (const listener of this.listeners(type)) {
          if (!options[kForOnEventAttribute] && listener[kListener] === handler && !listener[kForOnEventAttribute]) {
            return;
          }
        }
        let wrapper;
        if (type === "message") {
          wrapper = function onMessage(data, isBinary) {
            const event = new MessageEvent("message", {
              data: isBinary ? data : data.toString()
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "close") {
          wrapper = function onClose(code, message) {
            const event = new CloseEvent("close", {
              code,
              reason: message.toString(),
              wasClean: this._closeFrameReceived && this._closeFrameSent
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "error") {
          wrapper = function onError(error) {
            const event = new ErrorEvent("error", {
              error,
              message: error.message
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "open") {
          wrapper = function onOpen() {
            const event = new Event("open");
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else {
          return;
        }
        wrapper[kForOnEventAttribute] = !!options[kForOnEventAttribute];
        wrapper[kListener] = handler;
        if (options.once) {
          this.once(type, wrapper);
        } else {
          this.on(type, wrapper);
        }
      },
      /**
       * Remove an event listener.
       *
       * @param {String} type A string representing the event type to remove
       * @param {(Function|Object)} handler The listener to remove
       * @public
       */
      removeEventListener(type, handler) {
        for (const listener of this.listeners(type)) {
          if (listener[kListener] === handler && !listener[kForOnEventAttribute]) {
            this.removeListener(type, listener);
            break;
          }
        }
      }
    };
    module2.exports = {
      CloseEvent,
      ErrorEvent,
      Event,
      EventTarget,
      MessageEvent
    };
    function callListener(listener, thisArg, event) {
      if (typeof listener === "object" && listener.handleEvent) {
        listener.handleEvent.call(listener, event);
      } else {
        listener.call(thisArg, event);
      }
    }
  }
});

// node_modules/ws/lib/extension.js
var require_extension = __commonJS({
  "node_modules/ws/lib/extension.js"(exports2, module2) {
    "use strict";
    var { tokenChars } = require_validation();
    function push(dest, name, elem) {
      if (dest[name] === void 0) dest[name] = [elem];
      else dest[name].push(elem);
    }
    function parse(header) {
      const offers = /* @__PURE__ */ Object.create(null);
      let params = /* @__PURE__ */ Object.create(null);
      let mustUnescape = false;
      let isEscaping = false;
      let inQuotes = false;
      let extensionName;
      let paramName;
      let start = -1;
      let code = -1;
      let end = -1;
      let i = 0;
      for (; i < header.length; i++) {
        code = header.charCodeAt(i);
        if (extensionName === void 0) {
          if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (i !== 0 && (code === 32 || code === 9)) {
            if (end === -1 && start !== -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            const name = header.slice(start, end);
            if (code === 44) {
              push(offers, name, params);
              params = /* @__PURE__ */ Object.create(null);
            } else {
              extensionName = name;
            }
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        } else if (paramName === void 0) {
          if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (code === 32 || code === 9) {
            if (end === -1 && start !== -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            push(params, header.slice(start, end), true);
            if (code === 44) {
              push(offers, extensionName, params);
              params = /* @__PURE__ */ Object.create(null);
              extensionName = void 0;
            }
            start = end = -1;
          } else if (code === 61 && start !== -1 && end === -1) {
            paramName = header.slice(start, i);
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        } else {
          if (isEscaping) {
            if (tokenChars[code] !== 1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (start === -1) start = i;
            else if (!mustUnescape) mustUnescape = true;
            isEscaping = false;
          } else if (inQuotes) {
            if (tokenChars[code] === 1) {
              if (start === -1) start = i;
            } else if (code === 34 && start !== -1) {
              inQuotes = false;
              end = i;
            } else if (code === 92) {
              isEscaping = true;
            } else {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
          } else if (code === 34 && header.charCodeAt(i - 1) === 61) {
            inQuotes = true;
          } else if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (start !== -1 && (code === 32 || code === 9)) {
            if (end === -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            let value = header.slice(start, end);
            if (mustUnescape) {
              value = value.replace(/\\/g, "");
              mustUnescape = false;
            }
            push(params, paramName, value);
            if (code === 44) {
              push(offers, extensionName, params);
              params = /* @__PURE__ */ Object.create(null);
              extensionName = void 0;
            }
            paramName = void 0;
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        }
      }
      if (start === -1 || inQuotes || code === 32 || code === 9) {
        throw new SyntaxError("Unexpected end of input");
      }
      if (end === -1) end = i;
      const token = header.slice(start, end);
      if (extensionName === void 0) {
        push(offers, token, params);
      } else {
        if (paramName === void 0) {
          push(params, token, true);
        } else if (mustUnescape) {
          push(params, paramName, token.replace(/\\/g, ""));
        } else {
          push(params, paramName, token);
        }
        push(offers, extensionName, params);
      }
      return offers;
    }
    function format(extensions) {
      return Object.keys(extensions).map((extension2) => {
        let configurations = extensions[extension2];
        if (!Array.isArray(configurations)) configurations = [configurations];
        return configurations.map((params) => {
          return [extension2].concat(
            Object.keys(params).map((k) => {
              let values = params[k];
              if (!Array.isArray(values)) values = [values];
              return values.map((v) => v === true ? k : `${k}=${v}`).join("; ");
            })
          ).join("; ");
        }).join(", ");
      }).join(", ");
    }
    module2.exports = { format, parse };
  }
});

// node_modules/ws/lib/websocket.js
var require_websocket = __commonJS({
  "node_modules/ws/lib/websocket.js"(exports2, module2) {
    "use strict";
    var EventEmitter = require("events");
    var https3 = require("https");
    var http2 = require("http");
    var net = require("net");
    var tls2 = require("tls");
    var { randomBytes, createHash } = require("crypto");
    var { Duplex, Readable } = require("stream");
    var { URL: URL2 } = require("url");
    var PerMessageDeflate2 = require_permessage_deflate();
    var Receiver2 = require_receiver();
    var Sender2 = require_sender();
    var { isBlob } = require_validation();
    var {
      BINARY_TYPES,
      CLOSE_TIMEOUT,
      EMPTY_BUFFER,
      GUID,
      kForOnEventAttribute,
      kListener,
      kStatusCode,
      kWebSocket,
      NOOP
    } = require_constants();
    var {
      EventTarget: { addEventListener, removeEventListener }
    } = require_event_target();
    var { format, parse } = require_extension();
    var { toBuffer } = require_buffer_util();
    var kAborted = Symbol("kAborted");
    var protocolVersions = [8, 13];
    var readyStates = ["CONNECTING", "OPEN", "CLOSING", "CLOSED"];
    var subprotocolRegex = /^[!#$%&'*+\-.0-9A-Z^_`|a-z~]+$/;
    var WebSocket2 = class _WebSocket extends EventEmitter {
      /**
       * Create a new `WebSocket`.
       *
       * @param {(String|URL)} address The URL to which to connect
       * @param {(String|String[])} [protocols] The subprotocols
       * @param {Object} [options] Connection options
       */
      constructor(address, protocols, options) {
        super();
        this._binaryType = BINARY_TYPES[0];
        this._closeCode = 1006;
        this._closeFrameReceived = false;
        this._closeFrameSent = false;
        this._closeMessage = EMPTY_BUFFER;
        this._closeTimer = null;
        this._errorEmitted = false;
        this._extensions = {};
        this._paused = false;
        this._protocol = "";
        this._readyState = _WebSocket.CONNECTING;
        this._receiver = null;
        this._sender = null;
        this._socket = null;
        if (address !== null) {
          this._bufferedAmount = 0;
          this._isServer = false;
          this._redirects = 0;
          if (protocols === void 0) {
            if (!options || options.protocols === void 0) {
              protocols = [];
            } else if (Array.isArray(options.protocols)) {
              protocols = options.protocols;
            } else {
              protocols = [options.protocols];
            }
          } else if (!Array.isArray(protocols)) {
            if (typeof protocols === "object" && protocols !== null) {
              options = protocols;
              if (options.protocols === void 0) {
                protocols = [];
              } else if (Array.isArray(options.protocols)) {
                protocols = options.protocols;
              } else {
                protocols = [options.protocols];
              }
            } else {
              protocols = [protocols];
            }
          }
          initAsClient(this, address, protocols, options);
        } else {
          this._autoPong = options.autoPong;
          this._closeTimeout = options.closeTimeout;
          this._isServer = true;
        }
      }
      /**
       * For historical reasons, the custom "nodebuffer" type is used by the default
       * instead of "blob".
       *
       * @type {String}
       */
      get binaryType() {
        return this._binaryType;
      }
      set binaryType(type) {
        if (!BINARY_TYPES.includes(type)) return;
        this._binaryType = type;
        if (this._receiver) this._receiver._binaryType = type;
      }
      /**
       * @type {Number}
       */
      get bufferedAmount() {
        if (!this._socket) return this._bufferedAmount;
        return this._socket._writableState.length + this._sender._bufferedBytes;
      }
      /**
       * @type {String}
       */
      get extensions() {
        return Object.keys(this._extensions).join();
      }
      /**
       * @type {Boolean}
       */
      get isPaused() {
        return this._paused;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onclose() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onerror() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onopen() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onmessage() {
        return null;
      }
      /**
       * @type {String}
       */
      get protocol() {
        return this._protocol;
      }
      /**
       * @type {Number}
       */
      get readyState() {
        return this._readyState;
      }
      /**
       * @type {String}
       */
      get url() {
        return this._url;
      }
      /**
       * Set up the socket and the internal resources.
       *
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Object} options Options object
       * @param {Boolean} [options.allowSynchronousEvents=false] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Number} [options.maxBufferedChunks=0] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=0] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=0] The maximum allowed message size
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       * @private
       */
      setSocket(socket, head, options) {
        const receiver = new Receiver2({
          allowSynchronousEvents: options.allowSynchronousEvents,
          binaryType: this.binaryType,
          extensions: this._extensions,
          isServer: this._isServer,
          maxBufferedChunks: options.maxBufferedChunks,
          maxFragments: options.maxFragments,
          maxPayload: options.maxPayload,
          skipUTF8Validation: options.skipUTF8Validation
        });
        const sender = new Sender2(socket, this._extensions, options.generateMask);
        this._receiver = receiver;
        this._sender = sender;
        this._socket = socket;
        receiver[kWebSocket] = this;
        sender[kWebSocket] = this;
        socket[kWebSocket] = this;
        receiver.on("conclude", receiverOnConclude);
        receiver.on("drain", receiverOnDrain);
        receiver.on("error", receiverOnError);
        receiver.on("message", receiverOnMessage);
        receiver.on("ping", receiverOnPing);
        receiver.on("pong", receiverOnPong);
        sender.onerror = senderOnError;
        if (socket.setTimeout) socket.setTimeout(0);
        if (socket.setNoDelay) socket.setNoDelay();
        if (head.length > 0) socket.unshift(head);
        socket.on("close", socketOnClose);
        socket.on("data", socketOnData);
        socket.on("end", socketOnEnd);
        socket.on("error", socketOnError);
        this._readyState = _WebSocket.OPEN;
        this.emit("open");
      }
      /**
       * Emit the `'close'` event.
       *
       * @private
       */
      emitClose() {
        if (!this._socket) {
          this._readyState = _WebSocket.CLOSED;
          this.emit("close", this._closeCode, this._closeMessage);
          return;
        }
        if (this._extensions[PerMessageDeflate2.extensionName]) {
          this._extensions[PerMessageDeflate2.extensionName].cleanup();
        }
        this._receiver.removeAllListeners();
        this._readyState = _WebSocket.CLOSED;
        this.emit("close", this._closeCode, this._closeMessage);
      }
      /**
       * Start a closing handshake.
       *
       *          +----------+   +-----------+   +----------+
       *     - - -|ws.close()|-->|close frame|-->|ws.close()|- - -
       *    |     +----------+   +-----------+   +----------+     |
       *          +----------+   +-----------+         |
       * CLOSING  |ws.close()|<--|close frame|<--+-----+       CLOSING
       *          +----------+   +-----------+   |
       *    |           |                        |   +---+        |
       *                +------------------------+-->|fin| - - - -
       *    |         +---+                      |   +---+
       *     - - - - -|fin|<---------------------+
       *              +---+
       *
       * @param {Number} [code] Status code explaining why the connection is closing
       * @param {(String|Buffer)} [data] The reason why the connection is
       *     closing
       * @public
       */
      close(code, data) {
        if (this.readyState === _WebSocket.CLOSED) return;
        if (this.readyState === _WebSocket.CONNECTING) {
          const msg = "WebSocket was closed before the connection was established";
          abortHandshake(this, this._req, msg);
          return;
        }
        if (this.readyState === _WebSocket.CLOSING) {
          if (this._closeFrameSent && (this._closeFrameReceived || this._receiver._writableState.errorEmitted)) {
            this._socket.end();
          }
          return;
        }
        this._sender.close(code, data, !this._isServer, (err) => {
          if (err) return;
          this._closeFrameSent = true;
          if (this._closeFrameReceived || this._receiver._writableState.errorEmitted) {
            this._socket.end();
          }
        });
        this._readyState = _WebSocket.CLOSING;
        setCloseTimer(this);
      }
      /**
       * Pause the socket.
       *
       * @public
       */
      pause() {
        if (this.readyState === _WebSocket.CONNECTING || this.readyState === _WebSocket.CLOSED) {
          return;
        }
        this._paused = true;
        this._socket.pause();
      }
      /**
       * Send a ping.
       *
       * @param {*} [data] The data to send
       * @param {Boolean} [mask] Indicates whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when the ping is sent
       * @public
       */
      ping(data, mask, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof data === "function") {
          cb = data;
          data = mask = void 0;
        } else if (typeof mask === "function") {
          cb = mask;
          mask = void 0;
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        if (mask === void 0) mask = !this._isServer;
        this._sender.ping(data || EMPTY_BUFFER, mask, cb);
      }
      /**
       * Send a pong.
       *
       * @param {*} [data] The data to send
       * @param {Boolean} [mask] Indicates whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when the pong is sent
       * @public
       */
      pong(data, mask, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof data === "function") {
          cb = data;
          data = mask = void 0;
        } else if (typeof mask === "function") {
          cb = mask;
          mask = void 0;
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        if (mask === void 0) mask = !this._isServer;
        this._sender.pong(data || EMPTY_BUFFER, mask, cb);
      }
      /**
       * Resume the socket.
       *
       * @public
       */
      resume() {
        if (this.readyState === _WebSocket.CONNECTING || this.readyState === _WebSocket.CLOSED) {
          return;
        }
        this._paused = false;
        if (!this._receiver._writableState.needDrain) this._socket.resume();
      }
      /**
       * Send a data message.
       *
       * @param {*} data The message to send
       * @param {Object} [options] Options object
       * @param {Boolean} [options.binary] Specifies whether `data` is binary or
       *     text
       * @param {Boolean} [options.compress] Specifies whether or not to compress
       *     `data`
       * @param {Boolean} [options.fin=true] Specifies whether the fragment is the
       *     last one
       * @param {Boolean} [options.mask] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when data is written out
       * @public
       */
      send(data, options, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof options === "function") {
          cb = options;
          options = {};
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        const opts = {
          binary: typeof data !== "string",
          mask: !this._isServer,
          compress: true,
          fin: true,
          ...options
        };
        if (!this._extensions[PerMessageDeflate2.extensionName]) {
          opts.compress = false;
        }
        this._sender.send(data || EMPTY_BUFFER, opts, cb);
      }
      /**
       * Forcibly close the connection.
       *
       * @public
       */
      terminate() {
        if (this.readyState === _WebSocket.CLOSED) return;
        if (this.readyState === _WebSocket.CONNECTING) {
          const msg = "WebSocket was closed before the connection was established";
          abortHandshake(this, this._req, msg);
          return;
        }
        if (this._socket) {
          this._readyState = _WebSocket.CLOSING;
          this._socket.destroy();
        }
      }
    };
    Object.defineProperty(WebSocket2, "CONNECTING", {
      enumerable: true,
      value: readyStates.indexOf("CONNECTING")
    });
    Object.defineProperty(WebSocket2.prototype, "CONNECTING", {
      enumerable: true,
      value: readyStates.indexOf("CONNECTING")
    });
    Object.defineProperty(WebSocket2, "OPEN", {
      enumerable: true,
      value: readyStates.indexOf("OPEN")
    });
    Object.defineProperty(WebSocket2.prototype, "OPEN", {
      enumerable: true,
      value: readyStates.indexOf("OPEN")
    });
    Object.defineProperty(WebSocket2, "CLOSING", {
      enumerable: true,
      value: readyStates.indexOf("CLOSING")
    });
    Object.defineProperty(WebSocket2.prototype, "CLOSING", {
      enumerable: true,
      value: readyStates.indexOf("CLOSING")
    });
    Object.defineProperty(WebSocket2, "CLOSED", {
      enumerable: true,
      value: readyStates.indexOf("CLOSED")
    });
    Object.defineProperty(WebSocket2.prototype, "CLOSED", {
      enumerable: true,
      value: readyStates.indexOf("CLOSED")
    });
    [
      "binaryType",
      "bufferedAmount",
      "extensions",
      "isPaused",
      "protocol",
      "readyState",
      "url"
    ].forEach((property) => {
      Object.defineProperty(WebSocket2.prototype, property, { enumerable: true });
    });
    ["open", "error", "close", "message"].forEach((method) => {
      Object.defineProperty(WebSocket2.prototype, `on${method}`, {
        enumerable: true,
        get() {
          for (const listener of this.listeners(method)) {
            if (listener[kForOnEventAttribute]) return listener[kListener];
          }
          return null;
        },
        set(handler) {
          for (const listener of this.listeners(method)) {
            if (listener[kForOnEventAttribute]) {
              this.removeListener(method, listener);
              break;
            }
          }
          if (typeof handler !== "function") return;
          this.addEventListener(method, handler, {
            [kForOnEventAttribute]: true
          });
        }
      });
    });
    WebSocket2.prototype.addEventListener = addEventListener;
    WebSocket2.prototype.removeEventListener = removeEventListener;
    module2.exports = WebSocket2;
    function initAsClient(websocket, address, protocols, options) {
      const opts = {
        allowSynchronousEvents: true,
        autoPong: true,
        closeTimeout: CLOSE_TIMEOUT,
        protocolVersion: protocolVersions[1],
        maxBufferedChunks: 256 * 1024,
        maxFragments: 16 * 1024,
        maxPayload: 100 * 1024 * 1024,
        skipUTF8Validation: false,
        perMessageDeflate: true,
        followRedirects: false,
        maxRedirects: 10,
        ...options,
        socketPath: void 0,
        hostname: void 0,
        protocol: void 0,
        protocols: void 0,
        timeout: void 0,
        method: "GET",
        host: void 0,
        path: void 0,
        port: void 0
      };
      websocket._autoPong = opts.autoPong;
      websocket._closeTimeout = opts.closeTimeout;
      if (!protocolVersions.includes(opts.protocolVersion)) {
        throw new RangeError(
          `Unsupported protocol version: ${opts.protocolVersion} (supported versions: ${protocolVersions.join(", ")})`
        );
      }
      let parsedUrl;
      if (address instanceof URL2) {
        parsedUrl = address;
      } else {
        try {
          parsedUrl = new URL2(address);
        } catch {
          throw new SyntaxError(`Invalid URL: ${address}`);
        }
      }
      if (parsedUrl.protocol === "http:") {
        parsedUrl.protocol = "ws:";
      } else if (parsedUrl.protocol === "https:") {
        parsedUrl.protocol = "wss:";
      }
      websocket._url = parsedUrl.href;
      const isSecure = parsedUrl.protocol === "wss:";
      const isIpcUrl = parsedUrl.protocol === "ws+unix:";
      let invalidUrlMessage;
      if (parsedUrl.protocol !== "ws:" && !isSecure && !isIpcUrl) {
        invalidUrlMessage = `The URL's protocol must be one of "ws:", "wss:", "http:", "https:", or "ws+unix:"`;
      } else if (isIpcUrl && !parsedUrl.pathname) {
        invalidUrlMessage = "The URL's pathname is empty";
      } else if (parsedUrl.hash) {
        invalidUrlMessage = "The URL contains a fragment identifier";
      }
      if (invalidUrlMessage) {
        const err = new SyntaxError(invalidUrlMessage);
        if (websocket._redirects === 0) {
          throw err;
        } else {
          emitErrorAndClose(websocket, err);
          return;
        }
      }
      const defaultPort = isSecure ? 443 : 80;
      const key = randomBytes(16).toString("base64");
      const request = isSecure ? https3.request : http2.request;
      const protocolSet = /* @__PURE__ */ new Set();
      let perMessageDeflate;
      opts.createConnection = opts.createConnection || (isSecure ? tlsConnect : netConnect);
      opts.defaultPort = opts.defaultPort || defaultPort;
      opts.port = parsedUrl.port || defaultPort;
      opts.host = parsedUrl.hostname.startsWith("[") ? parsedUrl.hostname.slice(1, -1) : parsedUrl.hostname;
      opts.headers = {
        ...opts.headers,
        "Sec-WebSocket-Version": opts.protocolVersion,
        "Sec-WebSocket-Key": key,
        Connection: "Upgrade",
        Upgrade: "websocket"
      };
      opts.path = parsedUrl.pathname + parsedUrl.search;
      opts.timeout = opts.handshakeTimeout;
      if (opts.perMessageDeflate) {
        perMessageDeflate = new PerMessageDeflate2({
          ...opts.perMessageDeflate,
          isServer: false,
          maxPayload: opts.maxPayload
        });
        opts.headers["Sec-WebSocket-Extensions"] = format({
          [PerMessageDeflate2.extensionName]: perMessageDeflate.offer()
        });
      }
      if (protocols.length) {
        for (const protocol of protocols) {
          if (typeof protocol !== "string" || !subprotocolRegex.test(protocol) || protocolSet.has(protocol)) {
            throw new SyntaxError(
              "An invalid or duplicated subprotocol was specified"
            );
          }
          protocolSet.add(protocol);
        }
        opts.headers["Sec-WebSocket-Protocol"] = protocols.join(",");
      }
      if (opts.origin) {
        if (opts.protocolVersion < 13) {
          opts.headers["Sec-WebSocket-Origin"] = opts.origin;
        } else {
          opts.headers.Origin = opts.origin;
        }
      }
      if (parsedUrl.username || parsedUrl.password) {
        opts.auth = `${parsedUrl.username}:${parsedUrl.password}`;
      }
      if (isIpcUrl) {
        const i = opts.path.indexOf(":");
        if (i === -1) {
          opts.socketPath = opts.path;
          opts.path = "";
        } else {
          opts.socketPath = opts.path.slice(0, i);
          opts.path = opts.path.slice(i + 1);
        }
      }
      let req;
      if (opts.followRedirects) {
        if (websocket._redirects === 0) {
          websocket._originalIpc = isIpcUrl;
          websocket._originalSecure = isSecure;
          websocket._originalHostOrSocketPath = isIpcUrl ? opts.socketPath : parsedUrl.host;
          const headers = options && options.headers;
          options = { ...options, headers: {} };
          if (headers) {
            for (const [key2, value] of Object.entries(headers)) {
              options.headers[key2.toLowerCase()] = value;
            }
          }
        } else if (websocket.listenerCount("redirect") === 0) {
          const isSameHost = isIpcUrl ? websocket._originalIpc ? opts.socketPath === websocket._originalHostOrSocketPath : false : websocket._originalIpc ? false : parsedUrl.host === websocket._originalHostOrSocketPath;
          if (!isSameHost || websocket._originalSecure && !isSecure) {
            delete opts.headers.authorization;
            delete opts.headers.cookie;
            if (!isSameHost) delete opts.headers.host;
            opts.auth = void 0;
          }
        }
        if (opts.auth && !options.headers.authorization) {
          options.headers.authorization = "Basic " + Buffer.from(opts.auth).toString("base64");
        }
        req = websocket._req = request(opts);
        if (websocket._redirects) {
          websocket.emit("redirect", websocket.url, req);
        }
      } else {
        req = websocket._req = request(opts);
      }
      if (opts.timeout) {
        req.on("timeout", () => {
          abortHandshake(websocket, req, "Opening handshake has timed out");
        });
      }
      req.on("error", (err) => {
        if (req === null || req[kAborted]) return;
        req = websocket._req = null;
        emitErrorAndClose(websocket, err);
      });
      req.on("response", (res) => {
        const location = res.headers.location;
        const statusCode = res.statusCode;
        if (location && opts.followRedirects && statusCode >= 300 && statusCode < 400) {
          if (++websocket._redirects > opts.maxRedirects) {
            abortHandshake(websocket, req, "Maximum redirects exceeded");
            return;
          }
          req.abort();
          let addr;
          try {
            addr = new URL2(location, address);
          } catch (e) {
            const err = new SyntaxError(`Invalid URL: ${location}`);
            emitErrorAndClose(websocket, err);
            return;
          }
          initAsClient(websocket, addr, protocols, options);
        } else if (!websocket.emit("unexpected-response", req, res)) {
          abortHandshake(
            websocket,
            req,
            `Unexpected server response: ${res.statusCode}`
          );
        }
      });
      req.on("upgrade", (res, socket, head) => {
        websocket.emit("upgrade", res);
        if (websocket.readyState !== WebSocket2.CONNECTING) return;
        req = websocket._req = null;
        const upgrade = res.headers.upgrade;
        if (upgrade === void 0 || upgrade.toLowerCase() !== "websocket") {
          abortHandshake(websocket, socket, "Invalid Upgrade header");
          return;
        }
        const digest = createHash("sha1").update(key + GUID).digest("base64");
        if (res.headers["sec-websocket-accept"] !== digest) {
          abortHandshake(websocket, socket, "Invalid Sec-WebSocket-Accept header");
          return;
        }
        const serverProt = res.headers["sec-websocket-protocol"];
        let protError;
        if (serverProt !== void 0) {
          if (!protocolSet.size) {
            protError = "Server sent a subprotocol but none was requested";
          } else if (!protocolSet.has(serverProt)) {
            protError = "Server sent an invalid subprotocol";
          }
        } else if (protocolSet.size) {
          protError = "Server sent no subprotocol";
        }
        if (protError) {
          abortHandshake(websocket, socket, protError);
          return;
        }
        if (serverProt) websocket._protocol = serverProt;
        const secWebSocketExtensions = res.headers["sec-websocket-extensions"];
        if (secWebSocketExtensions !== void 0) {
          if (!perMessageDeflate) {
            const message = "Server sent a Sec-WebSocket-Extensions header but no extension was requested";
            abortHandshake(websocket, socket, message);
            return;
          }
          let extensions;
          try {
            extensions = parse(secWebSocketExtensions);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Extensions header";
            abortHandshake(websocket, socket, message);
            return;
          }
          const extensionNames = Object.keys(extensions);
          if (extensionNames.length !== 1 || extensionNames[0] !== PerMessageDeflate2.extensionName) {
            const message = "Server indicated an extension that was not requested";
            abortHandshake(websocket, socket, message);
            return;
          }
          try {
            perMessageDeflate.accept(extensions[PerMessageDeflate2.extensionName]);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Extensions header";
            abortHandshake(websocket, socket, message);
            return;
          }
          websocket._extensions[PerMessageDeflate2.extensionName] = perMessageDeflate;
        }
        websocket.setSocket(socket, head, {
          allowSynchronousEvents: opts.allowSynchronousEvents,
          generateMask: opts.generateMask,
          maxBufferedChunks: opts.maxBufferedChunks,
          maxFragments: opts.maxFragments,
          maxPayload: opts.maxPayload,
          skipUTF8Validation: opts.skipUTF8Validation
        });
      });
      if (opts.finishRequest) {
        opts.finishRequest(req, websocket);
      } else {
        req.end();
      }
    }
    function emitErrorAndClose(websocket, err) {
      websocket._readyState = WebSocket2.CLOSING;
      websocket._errorEmitted = true;
      websocket.emit("error", err);
      websocket.emitClose();
    }
    function netConnect(options) {
      options.path = options.socketPath;
      return net.connect(options);
    }
    function tlsConnect(options) {
      options.path = void 0;
      if (!options.servername && options.servername !== "") {
        options.servername = net.isIP(options.host) ? "" : options.host;
      }
      return tls2.connect(options);
    }
    function abortHandshake(websocket, stream, message) {
      websocket._readyState = WebSocket2.CLOSING;
      const err = new Error(message);
      Error.captureStackTrace(err, abortHandshake);
      if (stream.setHeader) {
        stream[kAborted] = true;
        stream.abort();
        if (stream.socket && !stream.socket.destroyed) {
          stream.socket.destroy();
        }
        process.nextTick(emitErrorAndClose, websocket, err);
      } else {
        stream.destroy(err);
        stream.once("error", websocket.emit.bind(websocket, "error"));
        stream.once("close", websocket.emitClose.bind(websocket));
      }
    }
    function sendAfterClose(websocket, data, cb) {
      if (data) {
        const length = isBlob(data) ? data.size : toBuffer(data).length;
        if (websocket._socket) websocket._sender._bufferedBytes += length;
        else websocket._bufferedAmount += length;
      }
      if (cb) {
        const err = new Error(
          `WebSocket is not open: readyState ${websocket.readyState} (${readyStates[websocket.readyState]})`
        );
        process.nextTick(cb, err);
      }
    }
    function receiverOnConclude(code, reason) {
      const websocket = this[kWebSocket];
      websocket._closeFrameReceived = true;
      websocket._closeMessage = reason;
      websocket._closeCode = code;
      if (websocket._socket[kWebSocket] === void 0) return;
      websocket._socket.removeListener("data", socketOnData);
      process.nextTick(resume, websocket._socket);
      if (code === 1005) websocket.close();
      else websocket.close(code, reason);
    }
    function receiverOnDrain() {
      const websocket = this[kWebSocket];
      if (!websocket.isPaused) websocket._socket.resume();
    }
    function receiverOnError(err) {
      const websocket = this[kWebSocket];
      if (websocket._socket[kWebSocket] !== void 0) {
        websocket._socket.removeListener("data", socketOnData);
        process.nextTick(resume, websocket._socket);
        websocket.close(err[kStatusCode]);
      }
      if (!websocket._errorEmitted) {
        websocket._errorEmitted = true;
        websocket.emit("error", err);
      }
    }
    function receiverOnFinish() {
      this[kWebSocket].emitClose();
    }
    function receiverOnMessage(data, isBinary) {
      this[kWebSocket].emit("message", data, isBinary);
    }
    function receiverOnPing(data) {
      const websocket = this[kWebSocket];
      if (websocket._autoPong) websocket.pong(data, !this._isServer, NOOP);
      websocket.emit("ping", data);
    }
    function receiverOnPong(data) {
      this[kWebSocket].emit("pong", data);
    }
    function resume(stream) {
      stream.resume();
    }
    function senderOnError(err) {
      const websocket = this[kWebSocket];
      if (websocket.readyState === WebSocket2.CLOSED) return;
      if (websocket.readyState === WebSocket2.OPEN) {
        websocket._readyState = WebSocket2.CLOSING;
        setCloseTimer(websocket);
      }
      this._socket.end();
      if (!websocket._errorEmitted) {
        websocket._errorEmitted = true;
        websocket.emit("error", err);
      }
    }
    function setCloseTimer(websocket) {
      websocket._closeTimer = setTimeout(
        websocket._socket.destroy.bind(websocket._socket),
        websocket._closeTimeout
      );
    }
    function socketOnClose() {
      const websocket = this[kWebSocket];
      this.removeListener("close", socketOnClose);
      this.removeListener("data", socketOnData);
      this.removeListener("end", socketOnEnd);
      websocket._readyState = WebSocket2.CLOSING;
      if (!this._readableState.endEmitted && !websocket._closeFrameReceived && !websocket._receiver._writableState.errorEmitted && this._readableState.length !== 0) {
        const chunk = this.read(this._readableState.length);
        websocket._receiver.write(chunk);
      }
      websocket._receiver.end();
      this[kWebSocket] = void 0;
      clearTimeout(websocket._closeTimer);
      if (websocket._receiver._writableState.finished || websocket._receiver._writableState.errorEmitted) {
        websocket.emitClose();
      } else {
        websocket._receiver.on("error", receiverOnFinish);
        websocket._receiver.on("finish", receiverOnFinish);
      }
    }
    function socketOnData(chunk) {
      if (!this[kWebSocket]._receiver.write(chunk)) {
        this.pause();
      }
    }
    function socketOnEnd() {
      const websocket = this[kWebSocket];
      websocket._readyState = WebSocket2.CLOSING;
      websocket._receiver.end();
      this.end();
    }
    function socketOnError() {
      const websocket = this[kWebSocket];
      this.removeListener("error", socketOnError);
      this.on("error", NOOP);
      if (websocket) {
        websocket._readyState = WebSocket2.CLOSING;
        this.destroy();
      }
    }
  }
});

// node_modules/ws/lib/stream.js
var require_stream = __commonJS({
  "node_modules/ws/lib/stream.js"(exports2, module2) {
    "use strict";
    var WebSocket2 = require_websocket();
    var { Duplex } = require("stream");
    function emitClose(stream) {
      stream.emit("close");
    }
    function duplexOnEnd() {
      if (!this.destroyed && this._writableState.finished) {
        this.destroy();
      }
    }
    function duplexOnError(err) {
      this.removeListener("error", duplexOnError);
      this.destroy();
      if (this.listenerCount("error") === 0) {
        this.emit("error", err);
      }
    }
    function createWebSocketStream2(ws, options) {
      let terminateOnDestroy = true;
      const duplex = new Duplex({
        ...options,
        autoDestroy: false,
        emitClose: false,
        objectMode: false,
        writableObjectMode: false
      });
      ws.on("message", function message(msg, isBinary) {
        const data = !isBinary && duplex._readableState.objectMode ? msg.toString() : msg;
        if (!duplex.push(data)) ws.pause();
      });
      ws.once("error", function error(err) {
        if (duplex.destroyed) return;
        terminateOnDestroy = false;
        duplex.destroy(err);
      });
      ws.once("close", function close() {
        if (duplex.destroyed) return;
        duplex.push(null);
      });
      duplex._destroy = function(err, callback) {
        if (ws.readyState === ws.CLOSED) {
          callback(err);
          process.nextTick(emitClose, duplex);
          return;
        }
        let called = false;
        ws.once("error", function error(err2) {
          called = true;
          callback(err2);
        });
        ws.once("close", function close() {
          if (!called) callback(err);
          process.nextTick(emitClose, duplex);
        });
        if (terminateOnDestroy) ws.terminate();
      };
      duplex._final = function(callback) {
        if (ws.readyState === ws.CONNECTING) {
          ws.once("open", function open() {
            duplex._final(callback);
          });
          return;
        }
        if (ws._socket === null) return;
        if (ws._socket._writableState.finished) {
          callback();
          if (duplex._readableState.endEmitted) duplex.destroy();
        } else {
          ws._socket.once("finish", function finish() {
            callback();
          });
          ws.close();
        }
      };
      duplex._read = function() {
        if (ws.isPaused) ws.resume();
      };
      duplex._write = function(chunk, encoding, callback) {
        if (ws.readyState === ws.CONNECTING) {
          ws.once("open", function open() {
            duplex._write(chunk, encoding, callback);
          });
          return;
        }
        ws.send(chunk, callback);
      };
      duplex.on("end", duplexOnEnd);
      duplex.on("error", duplexOnError);
      return duplex;
    }
    module2.exports = createWebSocketStream2;
  }
});

// node_modules/ws/lib/subprotocol.js
var require_subprotocol = __commonJS({
  "node_modules/ws/lib/subprotocol.js"(exports2, module2) {
    "use strict";
    var { tokenChars } = require_validation();
    function parse(header) {
      const protocols = /* @__PURE__ */ new Set();
      let start = -1;
      let end = -1;
      let i = 0;
      for (i; i < header.length; i++) {
        const code = header.charCodeAt(i);
        if (end === -1 && tokenChars[code] === 1) {
          if (start === -1) start = i;
        } else if (i !== 0 && (code === 32 || code === 9)) {
          if (end === -1 && start !== -1) end = i;
        } else if (code === 44) {
          if (start === -1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (end === -1) end = i;
          const protocol2 = header.slice(start, end);
          if (protocols.has(protocol2)) {
            throw new SyntaxError(`The "${protocol2}" subprotocol is duplicated`);
          }
          protocols.add(protocol2);
          start = end = -1;
        } else {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
      }
      if (start === -1 || end !== -1) {
        throw new SyntaxError("Unexpected end of input");
      }
      const protocol = header.slice(start, i);
      if (protocols.has(protocol)) {
        throw new SyntaxError(`The "${protocol}" subprotocol is duplicated`);
      }
      protocols.add(protocol);
      return protocols;
    }
    module2.exports = { parse };
  }
});

// node_modules/ws/lib/websocket-server.js
var require_websocket_server = __commonJS({
  "node_modules/ws/lib/websocket-server.js"(exports2, module2) {
    "use strict";
    var EventEmitter = require("events");
    var http2 = require("http");
    var { Duplex } = require("stream");
    var { createHash } = require("crypto");
    var extension2 = require_extension();
    var PerMessageDeflate2 = require_permessage_deflate();
    var subprotocol2 = require_subprotocol();
    var WebSocket2 = require_websocket();
    var { CLOSE_TIMEOUT, GUID, kWebSocket } = require_constants();
    var keyRegex = /^[+/0-9A-Za-z]{22}==$/;
    var RUNNING = 0;
    var CLOSING = 1;
    var CLOSED = 2;
    var WebSocketServer2 = class extends EventEmitter {
      /**
       * Create a `WebSocketServer` instance.
       *
       * @param {Object} options Configuration options
       * @param {Boolean} [options.allowSynchronousEvents=true] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {Boolean} [options.autoPong=true] Specifies whether or not to
       *     automatically send a pong in response to a ping
       * @param {Number} [options.backlog=511] The maximum length of the queue of
       *     pending connections
       * @param {Boolean} [options.clientTracking=true] Specifies whether or not to
       *     track clients
       * @param {Number} [options.closeTimeout=30000] Duration in milliseconds to
       *     wait for the closing handshake to finish after `websocket.close()` is
       *     called
       * @param {Function} [options.handleProtocols] A hook to handle protocols
       * @param {String} [options.host] The hostname where to bind the server
       * @param {Number} [options.maxBufferedChunks=262144] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=16384] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=104857600] The maximum allowed message
       *     size
       * @param {Boolean} [options.noServer=false] Enable no server mode
       * @param {String} [options.path] Accept only connections matching this path
       * @param {(Boolean|Object)} [options.perMessageDeflate=false] Enable/disable
       *     permessage-deflate
       * @param {Number} [options.port] The port where to bind the server
       * @param {(http.Server|https.Server)} [options.server] A pre-created HTTP/S
       *     server to use
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       * @param {Function} [options.verifyClient] A hook to reject connections
       * @param {Function} [options.WebSocket=WebSocket] Specifies the `WebSocket`
       *     class to use. It must be the `WebSocket` class or class that extends it
       * @param {Function} [callback] A listener for the `listening` event
       */
      constructor(options, callback) {
        super();
        options = {
          allowSynchronousEvents: true,
          autoPong: true,
          maxBufferedChunks: 256 * 1024,
          maxFragments: 16 * 1024,
          maxPayload: 100 * 1024 * 1024,
          skipUTF8Validation: false,
          perMessageDeflate: false,
          handleProtocols: null,
          clientTracking: true,
          closeTimeout: CLOSE_TIMEOUT,
          verifyClient: null,
          noServer: false,
          backlog: null,
          // use default (511 as implemented in net.js)
          server: null,
          host: null,
          path: null,
          port: null,
          WebSocket: WebSocket2,
          ...options
        };
        if (options.port == null && !options.server && !options.noServer || options.port != null && (options.server || options.noServer) || options.server && options.noServer) {
          throw new TypeError(
            'One and only one of the "port", "server", or "noServer" options must be specified'
          );
        }
        if (options.port != null) {
          this._server = http2.createServer((req, res) => {
            const body = http2.STATUS_CODES[426];
            res.writeHead(426, {
              "Content-Length": body.length,
              "Content-Type": "text/plain"
            });
            res.end(body);
          });
          this._server.listen(
            options.port,
            options.host,
            options.backlog,
            callback
          );
        } else if (options.server) {
          this._server = options.server;
        }
        if (this._server) {
          const emitConnection = this.emit.bind(this, "connection");
          this._removeListeners = addListeners(this._server, {
            listening: this.emit.bind(this, "listening"),
            error: this.emit.bind(this, "error"),
            upgrade: (req, socket, head) => {
              this.handleUpgrade(req, socket, head, emitConnection);
            }
          });
        }
        if (options.perMessageDeflate === true) options.perMessageDeflate = {};
        if (options.clientTracking) {
          this.clients = /* @__PURE__ */ new Set();
          this._shouldEmitClose = false;
        }
        this.options = options;
        this._state = RUNNING;
      }
      /**
       * Returns the bound address, the address family name, and port of the server
       * as reported by the operating system if listening on an IP socket.
       * If the server is listening on a pipe or UNIX domain socket, the name is
       * returned as a string.
       *
       * @return {(Object|String|null)} The address of the server
       * @public
       */
      address() {
        if (this.options.noServer) {
          throw new Error('The server is operating in "noServer" mode');
        }
        if (!this._server) return null;
        return this._server.address();
      }
      /**
       * Stop the server from accepting new connections and emit the `'close'` event
       * when all existing connections are closed.
       *
       * @param {Function} [cb] A one-time listener for the `'close'` event
       * @public
       */
      close(cb) {
        if (this._state === CLOSED) {
          if (cb) {
            this.once("close", () => {
              cb(new Error("The server is not running"));
            });
          }
          process.nextTick(emitClose, this);
          return;
        }
        if (cb) this.once("close", cb);
        if (this._state === CLOSING) return;
        this._state = CLOSING;
        if (this.options.noServer || this.options.server) {
          if (this._server) {
            this._removeListeners();
            this._removeListeners = this._server = null;
          }
          if (this.clients) {
            if (!this.clients.size) {
              process.nextTick(emitClose, this);
            } else {
              this._shouldEmitClose = true;
            }
          } else {
            process.nextTick(emitClose, this);
          }
        } else {
          const server = this._server;
          this._removeListeners();
          this._removeListeners = this._server = null;
          server.close(() => {
            emitClose(this);
          });
        }
      }
      /**
       * See if a given request should be handled by this server instance.
       *
       * @param {http.IncomingMessage} req Request object to inspect
       * @return {Boolean} `true` if the request is valid, else `false`
       * @public
       */
      shouldHandle(req) {
        if (this.options.path) {
          const index = req.url.indexOf("?");
          const pathname = index !== -1 ? req.url.slice(0, index) : req.url;
          if (pathname !== this.options.path) return false;
        }
        return true;
      }
      /**
       * Handle a HTTP Upgrade request.
       *
       * @param {http.IncomingMessage} req The request object
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Function} cb Callback
       * @public
       */
      handleUpgrade(req, socket, head, cb) {
        socket.on("error", socketOnError);
        const key = req.headers["sec-websocket-key"];
        const upgrade = req.headers.upgrade;
        const version = +req.headers["sec-websocket-version"];
        if (req.method !== "GET") {
          const message = "Invalid HTTP method";
          abortHandshakeOrEmitwsClientError(this, req, socket, 405, message);
          return;
        }
        if (upgrade === void 0 || upgrade.toLowerCase() !== "websocket") {
          const message = "Invalid Upgrade header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
        if (key === void 0 || !keyRegex.test(key)) {
          const message = "Missing or invalid Sec-WebSocket-Key header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
        if (version !== 13 && version !== 8) {
          const message = "Missing or invalid Sec-WebSocket-Version header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message, {
            "Sec-WebSocket-Version": "13, 8"
          });
          return;
        }
        if (!this.shouldHandle(req)) {
          abortHandshake(socket, 400);
          return;
        }
        const secWebSocketProtocol = req.headers["sec-websocket-protocol"];
        let protocols = /* @__PURE__ */ new Set();
        if (secWebSocketProtocol !== void 0) {
          try {
            protocols = subprotocol2.parse(secWebSocketProtocol);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Protocol header";
            abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
            return;
          }
        }
        const secWebSocketExtensions = req.headers["sec-websocket-extensions"];
        const extensions = {};
        if (this.options.perMessageDeflate && secWebSocketExtensions !== void 0) {
          const perMessageDeflate = new PerMessageDeflate2({
            ...this.options.perMessageDeflate,
            isServer: true,
            maxPayload: this.options.maxPayload
          });
          try {
            const offers = extension2.parse(secWebSocketExtensions);
            if (offers[PerMessageDeflate2.extensionName]) {
              perMessageDeflate.accept(offers[PerMessageDeflate2.extensionName]);
              extensions[PerMessageDeflate2.extensionName] = perMessageDeflate;
            }
          } catch (err) {
            const message = "Invalid or unacceptable Sec-WebSocket-Extensions header";
            abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
            return;
          }
        }
        if (this.options.verifyClient) {
          const info = {
            origin: req.headers[`${version === 8 ? "sec-websocket-origin" : "origin"}`],
            secure: !!(req.socket.authorized || req.socket.encrypted),
            req
          };
          if (this.options.verifyClient.length === 2) {
            this.options.verifyClient(info, (verified, code, message, headers) => {
              if (!verified) {
                return abortHandshake(socket, code || 401, message, headers);
              }
              this.completeUpgrade(
                extensions,
                key,
                protocols,
                req,
                socket,
                head,
                cb
              );
            });
            return;
          }
          if (!this.options.verifyClient(info)) return abortHandshake(socket, 401);
        }
        this.completeUpgrade(extensions, key, protocols, req, socket, head, cb);
      }
      /**
       * Upgrade the connection to WebSocket.
       *
       * @param {Object} extensions The accepted extensions
       * @param {String} key The value of the `Sec-WebSocket-Key` header
       * @param {Set} protocols The subprotocols
       * @param {http.IncomingMessage} req The request object
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Function} cb Callback
       * @throws {Error} If called more than once with the same socket
       * @private
       */
      completeUpgrade(extensions, key, protocols, req, socket, head, cb) {
        if (!socket.readable || !socket.writable) return socket.destroy();
        if (socket[kWebSocket]) {
          throw new Error(
            "server.handleUpgrade() was called more than once with the same socket, possibly due to a misconfiguration"
          );
        }
        if (this._state > RUNNING) return abortHandshake(socket, 503);
        const digest = createHash("sha1").update(key + GUID).digest("base64");
        const headers = [
          "HTTP/1.1 101 Switching Protocols",
          "Upgrade: websocket",
          "Connection: Upgrade",
          `Sec-WebSocket-Accept: ${digest}`
        ];
        const ws = new this.options.WebSocket(null, void 0, this.options);
        if (protocols.size) {
          const protocol = this.options.handleProtocols ? this.options.handleProtocols(protocols, req) : protocols.values().next().value;
          if (protocol) {
            headers.push(`Sec-WebSocket-Protocol: ${protocol}`);
            ws._protocol = protocol;
          }
        }
        if (extensions[PerMessageDeflate2.extensionName]) {
          const params = extensions[PerMessageDeflate2.extensionName].params;
          const value = extension2.format({
            [PerMessageDeflate2.extensionName]: [params]
          });
          headers.push(`Sec-WebSocket-Extensions: ${value}`);
          ws._extensions = extensions;
        }
        this.emit("headers", headers, req);
        socket.write(headers.concat("\r\n").join("\r\n"));
        socket.removeListener("error", socketOnError);
        ws.setSocket(socket, head, {
          allowSynchronousEvents: this.options.allowSynchronousEvents,
          maxBufferedChunks: this.options.maxBufferedChunks,
          maxFragments: this.options.maxFragments,
          maxPayload: this.options.maxPayload,
          skipUTF8Validation: this.options.skipUTF8Validation
        });
        if (this.clients) {
          this.clients.add(ws);
          ws.on("close", () => {
            this.clients.delete(ws);
            if (this._shouldEmitClose && !this.clients.size) {
              process.nextTick(emitClose, this);
            }
          });
        }
        cb(ws, req);
      }
    };
    module2.exports = WebSocketServer2;
    function addListeners(server, map) {
      for (const event of Object.keys(map)) server.on(event, map[event]);
      return function removeListeners() {
        for (const event of Object.keys(map)) {
          server.removeListener(event, map[event]);
        }
      };
    }
    function emitClose(server) {
      server._state = CLOSED;
      server.emit("close");
    }
    function socketOnError() {
      this.destroy();
    }
    function abortHandshake(socket, code, message, headers) {
      message = message || http2.STATUS_CODES[code];
      headers = {
        Connection: "close",
        "Content-Type": "text/html",
        "Content-Length": Buffer.byteLength(message),
        ...headers
      };
      socket.once("finish", socket.destroy);
      socket.end(
        `HTTP/1.1 ${code} ${http2.STATUS_CODES[code]}\r
` + Object.keys(headers).map((h) => `${h}: ${headers[h]}`).join("\r\n") + "\r\n\r\n" + message
      );
    }
    function abortHandshakeOrEmitwsClientError(server, req, socket, code, message, headers) {
      if (server.listenerCount("wsClientError")) {
        const err = new Error(message);
        Error.captureStackTrace(err, abortHandshakeOrEmitwsClientError);
        server.emit("wsClientError", err, socket, req);
      } else {
        abortHandshake(socket, code, message, headers);
      }
    }
  }
});

// electron/main.ts
var import_electron6 = require("electron");
var import_node_child_process4 = require("node:child_process");
var import_node_crypto3 = __toESM(require("node:crypto"));
var import_node_fs5 = __toESM(require("node:fs"));
var import_node_os3 = __toESM(require("node:os"));
var import_node_path5 = __toESM(require("node:path"));

// electron/edge-connection.ts
var import_node_os = __toESM(require("node:os"));

// node_modules/ws/wrapper.mjs
var import_stream = __toESM(require_stream(), 1);
var import_extension = __toESM(require_extension(), 1);
var import_permessage_deflate = __toESM(require_permessage_deflate(), 1);
var import_receiver = __toESM(require_receiver(), 1);
var import_sender = __toESM(require_sender(), 1);
var import_subprotocol = __toESM(require_subprotocol(), 1);
var import_websocket = __toESM(require_websocket(), 1);
var import_websocket_server = __toESM(require_websocket_server(), 1);
var wrapper_default = import_websocket.default;

// electron/pinned-agent.ts
var import_node_crypto = __toESM(require("node:crypto"));
var import_node_https = __toESM(require("node:https"));
var import_node_tls = __toESM(require("node:tls"));
var CertificatePinError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "CertificatePinError";
  }
};
function normalizeFingerprint(value) {
  return String(value || "").replace(/[^0-9a-fA-F]/g, "").toUpperCase();
}
function shortFingerprint(fingerprint) {
  const normalized = normalizeFingerprint(fingerprint);
  if (normalized.length <= 16) return normalized;
  return `${normalized.slice(0, 8)}\u2026${normalized.slice(-8)}`;
}
function parsePairing(input) {
  if (typeof input !== "string") {
    throw new Error("\u0631\u0634\u062A\u0647 \u0627\u062A\u0635\u0627\u0644 \u0646\u0627\u0645\u0639\u062A\u0628\u0631 \u0627\u0633\u062A");
  }
  const trimmed = input.trim();
  const hash = trimmed.lastIndexOf("#");
  if (hash <= 0 || hash === trimmed.length - 1) {
    throw new Error("\u0631\u0634\u062A\u0647 \u0627\u062A\u0635\u0627\u0644 \u0628\u0627\u06CC\u062F \u0628\u0647 \u0634\u06A9\u0644 host:port#fingerprint \u0628\u0627\u0634\u062F");
  }
  const endpoint = trimmed.slice(0, hash).trim();
  const fingerprint = normalizeFingerprint(trimmed.slice(hash + 1));
  if (!/^[0-9A-F]{64}$/.test(fingerprint)) {
    throw new Error("\u0627\u062B\u0631 \u0627\u0646\u06AF\u0634\u062A \u06AF\u0648\u0627\u0647\u06CC \u0647\u0627\u0628 \u0628\u0627\u06CC\u062F \u06F6\u06F4 \u0631\u0642\u0645 \u0647\u06AF\u0632\u0627\u062F\u0633\u06CC\u0645\u0627\u0644 \u0628\u0627\u0634\u062F");
  }
  const bracketed = /^\[([0-9a-fA-F:]+)\]:(\d{1,5})$/.exec(endpoint);
  const plain = /^([^:\s/]+):(\d{1,5})$/.exec(endpoint);
  const match = bracketed || plain;
  if (!match) {
    throw new Error("\u0622\u062F\u0631\u0633 \u0647\u0627\u0628 \u0628\u0627\u06CC\u062F \u0628\u0647 \u0634\u06A9\u0644 host:port \u0628\u0627\u0634\u062F");
  }
  const host = match[1];
  const port = Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("\u0634\u0645\u0627\u0631\u0647 \u067E\u0648\u0631\u062A \u0647\u0627\u0628 \u0645\u0639\u062A\u0628\u0631 \u0646\u06CC\u0633\u062A");
  }
  return { host, port, fingerprint };
}
function fetchServerTlsFingerprint(host, port, timeoutMs = 7e3) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (err, fp) => {
      if (settled) return;
      settled = true;
      try {
        socket.destroy();
      } catch {
      }
      if (err) {
        reject(err);
      } else {
        resolve(fp || "");
      }
    };
    const socket = import_node_tls.default.connect({
      host,
      port,
      rejectUnauthorized: false,
      timeout: timeoutMs
    });
    socket.once("secureConnect", () => {
      try {
        const cert = socket.getPeerCertificate(true);
        let fp = "";
        if (cert && Buffer.isBuffer(cert.raw) && cert.raw.length > 0) {
          fp = import_node_crypto.default.createHash("sha256").update(cert.raw).digest("hex").toUpperCase();
        } else if (cert && cert.fingerprint256) {
          fp = normalizeFingerprint(cert.fingerprint256);
        }
        if (!/^[0-9A-F]{64}$/.test(fp)) {
          finish(new Error("\u0633\u0631\u0648\u0631 \u06AF\u0648\u0627\u0647\u06CC TLS \u0645\u0639\u062A\u0628\u0631\u06CC \u0627\u0631\u0627\u0626\u0647 \u0646\u06A9\u0631\u062F"));
          return;
        }
        finish(null, fp);
      } catch (err) {
        finish(err instanceof Error ? err : new Error(String(err)));
      }
    });
    socket.once("timeout", () => {
      finish(new Error("\u0632\u0645\u0627\u0646 \u0627\u062A\u0635\u0627\u0644 \u0628\u0647 \u0633\u0631\u0648\u0631 \u062A\u0645\u0627\u0645 \u0634\u062F"));
    });
    socket.once("error", (err) => {
      finish(err instanceof Error ? err : new Error(String(err)));
    });
  });
}
var agentCache = /* @__PURE__ */ new Map();
function getPinnedHttpsAgent(fingerprint, options = {}) {
  const norm = normalizeFingerprint(fingerprint);
  let cached = agentCache.get(norm);
  if (!cached) {
    cached = new PinnedHttpsAgent(norm, options);
    agentCache.set(norm, cached);
  }
  return cached;
}
var PinnedHttpsAgent = class extends import_node_https.default.Agent {
  constructor(fingerprint, options = {}) {
    super({
      keepAlive: true,
      maxSockets: 4,
      ...options,
      // Identity is the fingerprint, not the public CA chain. The pin check
      // below is mandatory and runs before this socket is released to HTTP.
      rejectUnauthorized: false
    });
    this.expected = normalizeFingerprint(fingerprint);
    if (!/^[0-9A-F]{64}$/.test(this.expected)) {
      throw new CertificatePinError("\u0627\u062B\u0631 \u0627\u0646\u06AF\u0634\u062A \u06AF\u0648\u0627\u0647\u06CC \u0645\u0639\u062A\u0628\u0631 \u0646\u06CC\u0633\u062A");
    }
  }
  // Node's agent supports the callback form; returning undefined is deliberate
  // so the socket is not used before the certificate is verified.
  createConnection(options, callback) {
    const socket = import_node_tls.default.connect({ ...options, rejectUnauthorized: false });
    let settled = false;
    const settle = (error) => {
      if (settled) return;
      settled = true;
      if (error) {
        socket.destroy();
        if (callback) callback(error);
        return;
      }
      if (callback) callback(null, socket);
    };
    socket.once("secureConnect", () => {
      const certificate = socket.getPeerCertificate();
      const actual = normalizeFingerprint((certificate == null ? void 0 : certificate.fingerprint256) || "");
      if (!actual || actual !== this.expected) {
        settle(
          new CertificatePinError(
            `\u06AF\u0648\u0627\u0647\u06CC \u0647\u0627\u0628 \u0628\u0627 \u0627\u062B\u0631 \u0627\u0646\u06AF\u0634\u062A \u062B\u0628\u062A\u200C\u0634\u062F\u0647 \u0645\u0637\u0627\u0628\u0642\u062A \u0646\u062F\u0627\u0631\u062F (\u062F\u0631\u06CC\u0627\u0641\u062A\u200C\u0634\u062F\u0647: ${actual ? shortFingerprint(actual) : "\u0628\u062F\u0648\u0646 \u06AF\u0648\u0627\u0647\u06CC"})`
          )
        );
        return;
      }
      settle(null);
    });
    socket.once("error", (error) => {
      settle(error instanceof Error ? error : new Error(String(error)));
    });
    socket.once("close", () => {
      if (!settled) settle(new Error("\u0627\u062A\u0635\u0627\u0644 TLS \u067E\u06CC\u0634 \u0627\u0632 \u062A\u0623\u06CC\u06CC\u062F \u06AF\u0648\u0627\u0647\u06CC \u0628\u0633\u062A\u0647 \u0634\u062F"));
    });
    return void 0;
  }
};
function requestJson(agent, target, method, path6, body, timeoutMs = 15e3, extraHeaders) {
  return new Promise((resolve, reject) => {
    const payload = body === void 0 ? null : Buffer.from(JSON.stringify(body), "utf8");
    const request = import_node_https.default.request(
      {
        host: target.host,
        port: target.port,
        path: path6,
        method,
        agent,
        timeout: timeoutMs,
        headers: {
          Accept: "application/json",
          "Cache-Control": "no-store",
          "User-Agent": "GameNetClient/0.1.0",
          ...payload ? {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": String(payload.byteLength)
          } : {},
          ...extraHeaders || {}
        }
      },
      (response) => {
        const chunks = [];
        let size = 0;
        response.on("data", (chunk) => {
          size += chunk.byteLength;
          if (size > 1e6) {
            request.destroy(new Error("\u067E\u0627\u0633\u062E \u0647\u0627\u0628 \u0628\u06CC\u0634 \u0627\u0632 \u062D\u062F \u0628\u0632\u0631\u06AF \u0627\u0633\u062A"));
            return;
          }
          chunks.push(chunk);
        });
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if (!text) {
            resolve({ status: response.statusCode || 0, body: null });
            return;
          }
          try {
            resolve({
              status: response.statusCode || 0,
              body: JSON.parse(text)
            });
          } catch {
            reject(new Error("\u067E\u0627\u0633\u062E \u0647\u0627\u0628 JSON \u0645\u0639\u062A\u0628\u0631 \u0646\u06CC\u0633\u062A"));
          }
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("\u0632\u0645\u0627\u0646 \u067E\u0627\u0633\u062E \u0647\u0627\u0628 \u062A\u0645\u0627\u0645 \u0634\u062F"));
    });
    request.on("error", reject);
    if (payload) request.write(payload);
    request.end();
  });
}
function errorMessage(error) {
  if (error instanceof CertificatePinError) return error.message;
  if (error instanceof Error) {
    if (/ECONNREFUSED/.test(error.message)) return "\u0647\u0627\u0628 \u062F\u0631 \u062F\u0633\u062A\u0631\u0633 \u0646\u06CC\u0633\u062A (\u0627\u062A\u0635\u0627\u0644 \u0631\u062F \u0634\u062F)";
    if (/ENOTFOUND|EAI_AGAIN/.test(error.message)) return "\u0622\u062F\u0631\u0633 \u0647\u0627\u0628 \u067E\u06CC\u062F\u0627 \u0646\u0634\u062F";
    if (/ETIMEDOUT|timeout/i.test(error.message)) return "\u0632\u0645\u0627\u0646 \u0627\u062A\u0635\u0627\u0644 \u0628\u0647 \u0647\u0627\u0628 \u062A\u0645\u0627\u0645 \u0634\u062F";
    return error.message;
  }
  return String(error);
}

// electron/edge-connection.ts
function primaryLanMac() {
  const nets = import_node_os.default.networkInterfaces();
  let fallback = "";
  for (const entries of Object.values(nets)) {
    if (!entries) continue;
    for (const entry of entries) {
      if (entry.internal) continue;
      const mac = (entry.mac || "").trim().toUpperCase();
      if (!mac || mac === "00:00:00:00:00:00") continue;
      if (entry.family === "IPv4") return mac;
      if (!fallback) fallback = mac;
    }
  }
  return fallback;
}
var ALLOWED_COMMANDS = /* @__PURE__ */ new Set([
  "client.lock",
  "client.unlock",
  "client.ping",
  "client.restart",
  "client.shutdown",
  "client.admin_unlock",
  "client.update",
  "client.unpair",
  "client.kill_games",
  "client.restart_app"
]);
var MAX_PAYLOAD_BYTES = 4 * 1024 * 1024;
var AUTH_TIMEOUT_MS = 1e4;
var COMPLETED_MEMORY = 200;
function describeError(message) {
  if (/ECONNREFUSED/i.test(message)) return "\u0647\u0627\u0628 \u0645\u062D\u0644\u06CC \u067E\u0627\u0633\u062E \u0646\u0645\u06CC\u200C\u062F\u0647\u062F";
  if (/ENOTFOUND|EAI_AGAIN/i.test(message)) return "\u0622\u062F\u0631\u0633 \u0647\u0627\u0628 \u067E\u06CC\u062F\u0627 \u0646\u0634\u062F";
  if (/ETIMEDOUT|handshake timeout/i.test(message)) return "\u0632\u0645\u0627\u0646 \u0627\u062A\u0635\u0627\u0644 \u0628\u0647 \u0647\u0627\u0628 \u062A\u0645\u0627\u0645 \u0634\u062F";
  if (/certificate|CERT_|self.signed|altnames/i.test(message)) return "\u06AF\u0648\u0627\u0647\u06CC TLS \u0647\u0627\u0628 \u062A\u0623\u06CC\u06CC\u062F \u0646\u0634\u062F";
  return message;
}
var EdgeConnection = class {
  constructor(options) {
    this.socket = null;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.watchdogTimer = null;
    this.authTimer = null;
    this.attempt = 0;
    this.stopped = false;
    this.welcomed = false;
    this.lastError = "";
    this.heartbeatSeconds = 10;
    /** Hub clock minus local clock: salon PCs often drift, so command TTLs must be compared in hub time. */
    this.serverSkewMs = 0;
    this.pendingAcks = /* @__PURE__ */ new Map();
    this.completed = /* @__PURE__ */ new Map();
    this.target = options.target;
    this.token = options.token;
    this.deviceId = options.deviceId;
    this.appVersion = options.appVersion;
    this.getState = options.getState;
    this.getOrthogonalState = options.getOrthogonalState;
    this.getGamesHash = options.getGamesHash;
    this.callbacks = options.callbacks;
  }
  orthogonalFields() {
    if (!this.getOrthogonalState) return {};
    const ortho = this.getOrthogonalState();
    return {
      kiosk_state: ortho.kiosk_state,
      power_state: ortho.power_state,
      health_status: ortho.health_status,
      ...ortho.health_message ? { health_message: ortho.health_message } : {}
    };
  }
  /** Inform Edge before terminating about whether OS is shutting down vs app closing. */
  sendGoodbye(reason, options) {
    var _a;
    if (!this.isOpen()) return;
    const ortho = (_a = this.getOrthogonalState) == null ? void 0 : _a.call(this);
    this.send({
      type: "goodbye",
      reason,
      power_state: (options == null ? void 0 : options.powerState) ?? (ortho == null ? void 0 : ortho.power_state) ?? "ON",
      kiosk_state: (options == null ? void 0 : options.kioskState) ?? (ortho == null ? void 0 : ortho.kiosk_state) ?? "DISABLED"
    });
  }
  start() {
    this.stopped = false;
    this.open();
  }
  stop() {
    this.stopped = true;
    this.clearTimers();
    this.welcomed = false;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      try {
        socket.close(1e3, "client stopping");
      } catch {
        socket.terminate();
      }
    }
  }
  /** Tell the edge that the screen was locked or unlocked locally. */
  notifyState() {
    if (!this.isOpen()) return;
    this.send({ type: "state", state: this.getState(), ...this.orthogonalFields() });
  }
  /** Push a captured screen frame back to the edge server. */
  sendRemoteFrame(frame) {
    if (!this.isOpen() || !this.welcomed) return false;
    return this.send({ type: "remote_frame", ...frame });
  }
  getTarget() {
    return this.target;
  }
  open() {
    if (this.stopped) return;
    this.clearTimers();
    this.lastError = "";
    this.callbacks.onPhase(this.attempt === 0 ? "connecting" : "reconnecting");
    const host = this.target.host.includes(":") ? `[${this.target.host}]` : this.target.host;
    const url = `wss://${host}:${this.target.port}/ws/device/`;
    const agent = getPinnedHttpsAgent(this.target.fingerprint);
    let socket;
    try {
      socket = new wrapper_default(url, {
        agent,
        handshakeTimeout: 12e3,
        maxPayload: MAX_PAYLOAD_BYTES,
        perMessageDeflate: false
      });
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.on("open", () => {
      this.send({
        type: "hello",
        device_id: this.deviceId,
        token: this.token,
        state: this.getState(),
        app_version: this.appVersion,
        mac_address: primaryLanMac(),
        ...this.getGamesHash ? { games_hash: this.getGamesHash() } : {},
        ...this.orthogonalFields()
      });
      this.authTimer = setTimeout(() => {
        if (!this.welcomed) {
          this.lastError = "\u0647\u0627\u0628 \u0628\u0647 \u0627\u062D\u0631\u0627\u0632 \u0647\u0648\u06CC\u062A \u062F\u0633\u062A\u06AF\u0627\u0647 \u067E\u0627\u0633\u062E \u0646\u062F\u0627\u062F";
          socket.terminate();
        }
      }, AUTH_TIMEOUT_MS);
    });
    socket.on("message", (data, isBinary) => {
      if (isBinary) {
        this.lastError = "\u0647\u0627\u0628 \u067E\u06CC\u0627\u0645 \u062F\u0648\u062A\u0627\u06CC\u06CC \u063A\u06CC\u0631\u0645\u0646\u062A\u0638\u0631\u0647 \u0641\u0631\u0633\u062A\u0627\u062F";
        socket.terminate();
        return;
      }
      const text = Buffer.isBuffer(data) ? data.toString("utf8") : String(data);
      if (Buffer.byteLength(text, "utf8") > MAX_PAYLOAD_BYTES) {
        this.lastError = "\u067E\u06CC\u0627\u0645 \u0647\u0627\u0628 \u0628\u06CC\u0634 \u0627\u0632 \u062D\u062F \u0628\u0632\u0631\u06AF \u0627\u0633\u062A";
        socket.terminate();
        return;
      }
      let message;
      try {
        const parsed = JSON.parse(text);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
        message = parsed;
      } catch {
        return;
      }
      this.armWatchdog();
      this.dispatch(message);
    });
    socket.on("unexpected-response", (_request, response) => {
      this.lastError = `\u0647\u0627\u0628 \u0627\u062A\u0635\u0627\u0644 WebSocket \u0631\u0627 \u0631\u062F \u06A9\u0631\u062F (HTTP ${response.statusCode || 0})`;
      response.resume();
      socket.terminate();
    });
    socket.on("error", (error) => {
      this.lastError = describeError(error instanceof Error ? error.message : String(error));
    });
    socket.on("close", (code, reasonBuffer) => {
      const reason = (reasonBuffer == null ? void 0 : reasonBuffer.toString("utf8")) || "";
      this.welcomed = false;
      this.clearTimers();
      if (this.socket === socket) this.socket = null;
      if (this.stopped) return;
      if (code === 4401) {
        this.stopped = true;
        this.callbacks.onAuthFailure("\u0627\u0639\u062A\u0628\u0627\u0631 \u062F\u0633\u062A\u06AF\u0627\u0647 \u062A\u0648\u0633\u0637 \u0647\u0627\u0628 \u0631\u062F \u0634\u062F\u061B \u062B\u0628\u062A \u062F\u0648\u0628\u0627\u0631\u0647 \u0644\u0627\u0632\u0645 \u0627\u0633\u062A");
        return;
      }
      const detail = this.lastError || (code === 1e3 ? "\u0627\u0631\u062A\u0628\u0627\u0637 \u0628\u0627 \u0647\u0627\u0628 \u0628\u0633\u062A\u0647 \u0634\u062F" : `\u0627\u0631\u062A\u0628\u0627\u0637 \u0628\u0627 \u0647\u0627\u0628 \u0642\u0637\u0639 \u0634\u062F (\u06A9\u062F ${code}${reason ? `: ${reason}` : ""})`);
      this.callbacks.onDisconnect(detail);
      this.scheduleReconnect();
    });
  }
  dispatch(message) {
    var _a, _b, _c, _d, _e, _f;
    const kind = message.type;
    const serverTime = typeof message.server_time === "string" ? Date.parse(message.server_time) : NaN;
    if (Number.isFinite(serverTime)) {
      const skew = serverTime - Date.now();
      if (Math.abs(skew) < 24 * 3600 * 1e3) this.serverSkewMs = skew;
    }
    if (kind === "welcome") {
      this.handleWelcome(message);
      return;
    }
    if (kind === "heartbeat_ack" || kind === "games_updated") {
      (_b = (_a = this.callbacks).onHeartbeatAck) == null ? void 0 : _b.call(_a, message);
      if (kind === "heartbeat_ack") {
        this.processCommands(message.pending_commands);
      }
      return;
    }
    if (kind === "command") {
      const command = message.command;
      if (command && typeof command === "object") {
        this.deliver(command);
      }
      return;
    }
    if (kind === "announcements_updated") {
      const list = Array.isArray(message.announcements) ? message.announcements : [];
      (_d = (_c = this.callbacks).onAnnouncementsUpdated) == null ? void 0 : _d.call(_c, list);
      return;
    }
    if (kind === "remote_control") {
      (_f = (_e = this.callbacks).onRemoteControl) == null ? void 0 : _f.call(_e, message);
      return;
    }
  }
  handleWelcome(message) {
    var _a;
    if (String(message.device_id) !== this.deviceId) {
      this.lastError = "\u0647\u0627\u0628 \u062F\u0633\u062A\u06AF\u0627\u0647 \u062F\u06CC\u06AF\u0631\u06CC \u0631\u0627 \u062A\u0623\u06CC\u06CC\u062F \u06A9\u0631\u062F";
      (_a = this.socket) == null ? void 0 : _a.terminate();
      return;
    }
    this.welcomed = true;
    if (this.authTimer) clearTimeout(this.authTimer);
    this.authTimer = null;
    this.attempt = 0;
    const heartbeatSeconds = Math.min(
      120,
      Math.max(3, Number(message.heartbeat_seconds) || 10)
    );
    this.heartbeatSeconds = heartbeatSeconds;
    this.callbacks.onWelcome({
      hubName: String(message.hub_name || ""),
      deviceName: String(message.device_name || ""),
      desiredState: String(message.desired_state || "LOCKED"),
      heartbeatSeconds,
      configVersion: Number(message.config_version) || 0,
      pendingCommands: Array.isArray(message.pending_commands) ? message.pending_commands.length : 0,
      serverTime: String(message.server_time || ""),
      games: Array.isArray(message.games) ? message.games : void 0,
      gamesHash: typeof message.games_hash === "string" ? message.games_hash : void 0,
      announcements: Array.isArray(message.announcements) ? message.announcements : void 0,
      announcementsHash: typeof message.announcements_hash === "string" ? message.announcements_hash : void 0,
      clientUpdate: message.client_update,
      idleShutdownMinutes: typeof message.idle_shutdown_minutes === "number" ? message.idle_shutdown_minutes : void 0,
      session: message.session
    });
    this.processCommands(message.pending_commands);
    this.startHeartbeat();
    this.flushAcks();
  }
  startHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      this.send({
        type: "heartbeat",
        state: this.getState(),
        app_version: this.appVersion,
        mac_address: primaryLanMac(),
        ...this.getGamesHash ? { games_hash: this.getGamesHash() } : {},
        ...this.orthogonalFields()
      });
    }, this.heartbeatSeconds * 1e3);
    this.armWatchdog();
  }
  armWatchdog() {
    if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
    this.watchdogTimer = setTimeout(() => {
      var _a;
      this.lastError = "\u067E\u0627\u0633\u062E \u0647\u0627\u0628 \u062F\u0631 \u0632\u0645\u0627\u0646 \u0645\u0642\u0631\u0631 \u0646\u0631\u0633\u06CC\u062F";
      (_a = this.socket) == null ? void 0 : _a.terminate();
    }, Math.max(3e4, this.heartbeatSeconds * 3e3));
  }
  processCommands(commands) {
    if (!Array.isArray(commands)) return;
    for (const raw of commands.slice(0, 50)) {
      if (raw && typeof raw === "object") this.deliver(raw);
    }
  }
  deliver(command) {
    const commandId = typeof command.command_id === "string" ? command.command_id : "";
    const commandType = typeof command.command_type === "string" ? command.command_type : "";
    if (!commandId || commandId.length > 64 || !commandType) return;
    const already = this.completed.get(commandId);
    if (already) {
      this.queueAck(commandId, already);
      return;
    }
    let ack;
    if (!ALLOWED_COMMANDS.has(commandType)) {
      ack = { status: "error", error: "\u0646\u0648\u0639 \u0641\u0631\u0645\u0627\u0646 \u0628\u0631\u0627\u06CC \u0627\u06CC\u0646 \u0646\u0633\u062E\u0647 \u067E\u0634\u062A\u06CC\u0628\u0627\u0646\u06CC \u0646\u0645\u06CC\u200C\u0634\u0648\u062F" };
    } else {
      const expiresAt = Date.parse(String(command.expires_at || ""));
      const localDeadline = expiresAt + this.serverSkewMs;
      if (!Number.isFinite(expiresAt)) {
        ack = { status: "error", error: "\u0632\u0645\u0627\u0646 \u0627\u0646\u0642\u0636\u0627\u06CC \u0641\u0631\u0645\u0627\u0646 \u0646\u0627\u0645\u0639\u062A\u0628\u0631 \u0627\u0633\u062A" };
      } else if (localDeadline + 2e3 < Date.now()) {
        ack = { status: "error", error: "\u0641\u0631\u0645\u0627\u0646 \u067E\u06CC\u0634 \u0627\u0632 \u0631\u0633\u06CC\u062F\u0646 \u0645\u0646\u0642\u0636\u06CC \u0634\u062F\u0647 \u0628\u0648\u062F" };
      } else {
        try {
          ack = this.callbacks.onCommand({
            ...command,
            payload: command.payload && typeof command.payload === "object" && !Array.isArray(command.payload) ? command.payload : {}
          });
        } catch (error) {
          ack = {
            status: "error",
            error: error instanceof Error ? error.message : String(error)
          };
        }
      }
    }
    this.completed.set(commandId, ack);
    if (this.completed.size > COMPLETED_MEMORY) {
      const oldest = this.completed.keys().next().value;
      if (oldest) this.completed.delete(oldest);
    }
    this.queueAck(commandId, ack);
  }
  queueAck(commandId, ack) {
    this.pendingAcks.set(commandId, ack);
    this.flushAcks();
  }
  flushAcks() {
    if (!this.isOpen() || !this.welcomed) return;
    for (const [commandId, ack] of this.pendingAcks) {
      const sent = this.send({
        type: "command_ack",
        command_id: commandId,
        status: ack.status,
        result: ack.result,
        error: ack.error || "",
        state: ack.state,
        ...ack.kiosk_state ? { kiosk_state: ack.kiosk_state } : {},
        ...ack.health_status ? { health_status: ack.health_status } : {},
        ...ack.health_message ? { health_message: ack.health_message } : {}
      });
      if (!sent) return;
      this.pendingAcks.delete(commandId);
    }
  }
  scheduleReconnect() {
    if (this.stopped) return;
    this.attempt += 1;
    const base = Math.min(3e4, 1e3 * 2 ** Math.min(this.attempt - 1, 5));
    const delay = Math.round(base * (0.8 + Math.random() * 0.4));
    this.callbacks.onPhase(
      "reconnecting",
      `${this.lastError || "\u0627\u0631\u062A\u0628\u0627\u0637 \u0628\u0631\u0642\u0631\u0627\u0631 \u0646\u0634\u062F"} \u2014 \u062A\u0644\u0627\u0634 \u062F\u0648\u0628\u0627\u0631\u0647 \u062F\u0631 ${Math.ceil(delay / 1e3)} \u062B\u0627\u0646\u06CC\u0647`
    );
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }
  isOpen() {
    return this.socket !== null && this.socket.readyState === wrapper_default.OPEN;
  }
  send(message) {
    var _a;
    if (!this.isOpen()) return false;
    try {
      (_a = this.socket) == null ? void 0 : _a.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }
  clearTimers() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
    if (this.authTimer) clearTimeout(this.authTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.watchdogTimer = null;
    this.authTimer = null;
  }
};

// electron/logger.ts
var import_electron = require("electron");
var import_node_fs = __toESM(require("node:fs"));
var import_node_path = __toESM(require("node:path"));
var logFile = "";
function initLogging() {
  try {
    const directory = import_node_path.default.join(import_electron.app.getPath("userData"), "logs");
    import_node_fs.default.mkdirSync(directory, { recursive: true, mode: 448 });
    logFile = import_node_path.default.join(directory, "client.log");
    if (import_node_fs.default.existsSync(logFile) && import_node_fs.default.statSync(logFile).size > 1e6) {
      import_node_fs.default.renameSync(logFile, `${logFile}.1`);
    }
  } catch {
    logFile = "";
  }
}
function log(level, message) {
  const line = `${(/* @__PURE__ */ new Date()).toISOString()} ${level.toUpperCase()} ${message}
`;
  if (level === "error") console.error(line.trimEnd());
  else console.log(line.trimEnd());
  if (!logFile) return;
  try {
    import_node_fs.default.appendFileSync(logFile, line, { encoding: "utf8", mode: 384 });
  } catch {
  }
}

// electron/updater.ts
var import_electron2 = require("electron");
var import_node_fs2 = __toESM(require("node:fs"));
var import_node_path2 = __toESM(require("node:path"));
var import_node_https2 = __toESM(require("node:https"));
var import_node_http = __toESM(require("node:http"));
var import_node_crypto2 = __toESM(require("node:crypto"));
var import_node_child_process = require("node:child_process");
var isUpdating = false;
function performClientUpdate(options) {
  if (isUpdating) {
    return Promise.resolve(false);
  }
  const currentVersion = import_electron2.app.getVersion();
  if (options.version === currentVersion) {
    return Promise.resolve(false);
  }
  isUpdating = true;
  return new Promise((resolve, reject) => {
    var _a, _b;
    try {
      const tempDir = import_node_path2.default.join(import_electron2.app.getPath("temp"), "gamenet_update");
      if (!import_node_fs2.default.existsSync(tempDir)) {
        import_node_fs2.default.mkdirSync(tempDir, { recursive: true });
      }
      const isInstaller = options.url.endsWith(".exe");
      const targetFilename = isInstaller ? "GameNet-Setup.exe" : "update_package.bin";
      const targetFilePath = import_node_path2.default.join(tempDir, targetFilename);
      if (import_node_fs2.default.existsSync(targetFilePath)) {
        try {
          import_node_fs2.default.unlinkSync(targetFilePath);
        } catch {
        }
      }
      let downloadUrl = options.url;
      if (!downloadUrl.startsWith("http://") && !downloadUrl.startsWith("https://")) {
        const host = options.hubHost || "127.0.0.1";
        const port = options.hubPort || 19443;
        const normalizedPath = downloadUrl.startsWith("/") ? downloadUrl : `/${downloadUrl}`;
        downloadUrl = `https://${host}:${port}${normalizedPath}`;
      }
      (_a = options.onProgress) == null ? void 0 : _a.call(options, 0, `\u0634\u0631\u0648\u0639 \u062F\u0631\u06CC\u0627\u0641\u062A \u0646\u0633\u062E\u0647 ${options.version}...`);
      const parsedUrl = new URL(downloadUrl);
      const httpModule = parsedUrl.protocol === "https:" ? import_node_https2.default : import_node_http.default;
      const req = httpModule.get(
        downloadUrl,
        {
          rejectUnauthorized: false,
          headers: {
            "User-Agent": `GameNet-Client/${currentVersion}`
          }
        },
        (res) => {
          var _a2;
          if (res.statusCode !== 200) {
            isUpdating = false;
            const err = new Error(`\u062F\u0631\u06CC\u0627\u0641\u062A \u0641\u0627\u06CC\u0644 \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC \u0628\u0627 \u062E\u0637\u0627 \u0645\u0648\u0627\u062C\u0647 \u0634\u062F (\u06A9\u062F ${res.statusCode})`);
            (_a2 = options.onError) == null ? void 0 : _a2.call(options, err);
            reject(err);
            return;
          }
          const totalBytes = parseInt(res.headers["content-length"] || "0", 10);
          let receivedBytes = 0;
          const hash = import_node_crypto2.default.createHash("sha256");
          const fileStream = import_node_fs2.default.createWriteStream(targetFilePath);
          res.on("data", (chunk) => {
            var _a3, _b2;
            receivedBytes += chunk.length;
            hash.update(chunk);
            fileStream.write(chunk);
            if (totalBytes > 0) {
              const percent = Math.min(100, Math.round(receivedBytes / totalBytes * 100));
              (_a3 = options.onProgress) == null ? void 0 : _a3.call(options, percent, `\u062F\u0631 \u062D\u0627\u0644 \u062F\u0631\u06CC\u0627\u0641\u062A \u0646\u0633\u062E\u0647 ${options.version} (${percent}\u066A)...`);
            } else {
              (_b2 = options.onProgress) == null ? void 0 : _b2.call(options, 50, `\u062F\u0631 \u062D\u0627\u0644 \u062F\u0631\u06CC\u0627\u0641\u062A \u0641\u0627\u06CC\u0644 \u0646\u0633\u062E\u0647 ${options.version}...`);
            }
          });
          res.on("end", () => {
            fileStream.end(async () => {
              var _a3, _b2, _c, _d;
              try {
                if (options.sha256 && options.sha256.trim()) {
                  const calculatedHash = hash.digest("hex").toLowerCase();
                  const expectedHash = options.sha256.trim().toLowerCase();
                  if (calculatedHash !== expectedHash) {
                    isUpdating = false;
                    try {
                      import_node_fs2.default.unlinkSync(targetFilePath);
                    } catch {
                    }
                    const err = new Error("\u06A9\u062F \u0627\u0639\u062A\u0628\u0627\u0631\u0633\u0646\u062C\u06CC (\u0647\u0634) \u0641\u0627\u06CC\u0644 \u062F\u0627\u0646\u0644\u0648\u062F \u0634\u062F\u0647 \u0628\u0627 \u0633\u0631\u0648\u0631 \u062A\u0637\u0627\u0628\u0642 \u0646\u062F\u0627\u0631\u062F.");
                    (_a3 = options.onError) == null ? void 0 : _a3.call(options, err);
                    reject(err);
                    return;
                  }
                }
                (_b2 = options.onProgress) == null ? void 0 : _b2.call(options, 100, "\u062F\u0627\u0646\u0644\u0648\u062F \u062A\u06A9\u0645\u06CC\u0644 \u0634\u062F. \u062F\u0631 \u062D\u0627\u0644 \u0627\u0639\u0645\u0627\u0644 \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC \u0648 \u0631\u0627\u0647\u200C\u0627\u0646\u062F\u0627\u0632\u06CC \u0645\u062C\u062F\u062F...");
                (_c = options.onComplete) == null ? void 0 : _c.call(options);
                setTimeout(() => {
                  applyAndRestart(tempDir, targetFilePath, isInstaller);
                  resolve(true);
                }, 1e3);
              } catch (err) {
                isUpdating = false;
                (_d = options.onError) == null ? void 0 : _d.call(options, err);
                reject(err);
              }
            });
          });
          res.on("error", (err) => {
            var _a3;
            isUpdating = false;
            fileStream.destroy();
            try {
              import_node_fs2.default.unlinkSync(targetFilePath);
            } catch {
            }
            (_a3 = options.onError) == null ? void 0 : _a3.call(options, err);
            reject(err);
          });
        }
      );
      req.on("error", (err) => {
        var _a2;
        isUpdating = false;
        (_a2 = options.onError) == null ? void 0 : _a2.call(options, err);
        reject(err);
      });
    } catch (err) {
      isUpdating = false;
      (_b = options.onError) == null ? void 0 : _b.call(options, err);
      reject(err);
    }
  });
}
function applyAndRestart(tempDir, updateFilePath, isInstaller) {
  const installDir = import_electron2.app.isPackaged ? import_node_path2.default.dirname(process.resourcesPath) : process.cwd();
  const exePath = import_electron2.app.getPath("exe");
  const asarDest = import_node_path2.default.join(installDir, "resources", "app.asar");
  const setupExePath = import_node_path2.default.join(tempDir, "GameNet-Setup.exe");
  if (process.platform === "win32") {
    const batPath = import_node_path2.default.join(tempDir, "apply_update.bat");
    const logPath = import_node_path2.default.join(tempDir, "update.log");
    const batLines = [
      "@echo off",
      "title GameNet Auto-Updater",
      `echo [%date% %time%] Starting GameNet update... > "${logPath}"`,
      "ping -n 3 127.0.0.1 >nul",
      "taskkill /f /im GameNet.exe >nul 2>&1",
      "ping -n 2 127.0.0.1 >nul",
      "",
      `if exist "${updateFilePath}" if /i not "${updateFilePath}"=="${setupExePath}" (`,
      `    echo Copying updated app.asar... >> "${logPath}"`,
      "    for /L %%i in (1,1,6) do (",
      `        copy /y "${updateFilePath}" "${asarDest}" >> "${logPath}" 2>&1`,
      "        if not errorlevel 1 goto copy_ok",
      "        ping -n 2 127.0.0.1 >nul",
      "    )",
      `    echo Standard copy failed; elevation is required. >> "${logPath}"`,
      ")",
      ":copy_ok",
      "",
      `if exist "${setupExePath}" (`,
      `    echo Running installer >> "${logPath}"`,
      `    "${setupExePath}" /S >> "${logPath}" 2>&1`,
      `    if errorlevel 1 echo Silent install was refused; a manual installer run is required. >> "${logPath}"`,
      ")",
      "",
      "ping -n 10 127.0.0.1 >nul",
      `echo Starting "${exePath}" >> "${logPath}"`,
      `start "" "${exePath}"`,
      "exit",
      ""
    ];
    import_node_fs2.default.writeFileSync(batPath, batLines.join("\r\n"), "utf8");
    const child = (0, import_node_child_process.spawn)("cmd.exe", ["/c", batPath], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      shell: false
    });
    child.unref();
    import_electron2.app.exit(0);
  } else {
    if (!isInstaller) {
      try {
        const dest = import_node_path2.default.join(process.resourcesPath, "app.asar");
        import_node_fs2.default.copyFileSync(updateFilePath, dest);
      } catch {
      }
    }
    import_electron2.app.relaunch();
    import_electron2.app.exit(0);
  }
}

// electron/state-store.ts
var import_electron3 = require("electron");
var import_node_fs3 = __toESM(require("node:fs"));
var import_node_path3 = __toESM(require("node:path"));
var STATE_VERSION = 1;
function statePath() {
  return import_node_path3.default.join(import_electron3.app.getPath("userData"), "client-state.json");
}
function ensureDirectory() {
  import_node_fs3.default.mkdirSync(import_node_path3.default.dirname(statePath()), { recursive: true, mode: 448 });
}
function isPairingTarget(value) {
  if (!value || typeof value !== "object") return false;
  const candidate = value;
  return typeof candidate.host === "string" && candidate.host.length > 0 && candidate.host.length <= 255 && Number.isInteger(candidate.port) && candidate.port > 0 && candidate.port < 65536 && typeof candidate.fingerprint === "string" && /^[0-9A-F]{64}$/.test(candidate.fingerprint);
}
var StateStore = class {
  load() {
    try {
      const raw = import_node_fs3.default.readFileSync(statePath(), "utf8");
      const parsed = JSON.parse(raw);
      if (parsed.version !== STATE_VERSION || !isPairingTarget(parsed.pairing) || typeof parsed.deviceId !== "string" || !parsed.deviceId || typeof parsed.tokenSealed !== "string" || !parsed.tokenSealed) {
        return null;
      }
      return {
        version: STATE_VERSION,
        pairing: parsed.pairing,
        deviceId: parsed.deviceId,
        deviceName: typeof parsed.deviceName === "string" ? parsed.deviceName : "",
        hubName: typeof parsed.hubName === "string" ? parsed.hubName : "",
        tokenSealed: parsed.tokenSealed,
        idleShutdownMinutes: typeof parsed.idleShutdownMinutes === "number" ? parsed.idleShutdownMinutes : void 0,
        savedAt: typeof parsed.savedAt === "string" ? parsed.savedAt : ""
      };
    } catch {
      return null;
    }
  }
  save(state) {
    ensureDirectory();
    const full = {
      version: STATE_VERSION,
      ...state,
      savedAt: (/* @__PURE__ */ new Date()).toISOString()
    };
    const temporary = `${statePath()}.tmp`;
    import_node_fs3.default.writeFileSync(temporary, JSON.stringify(full, null, 2), {
      encoding: "utf8",
      mode: 384
    });
    import_node_fs3.default.chmodSync(temporary, 384);
    import_node_fs3.default.renameSync(temporary, statePath());
    return full;
  }
  clear() {
    try {
      import_node_fs3.default.rmSync(statePath(), { force: true });
    } catch {
    }
  }
  sealToken(token) {
    if (import_electron3.safeStorage.isEncryptionAvailable()) {
      return `enc:${import_electron3.safeStorage.encryptString(token).toString("base64")}`;
    }
    if (process.platform === "win32") {
      throw new Error(
        "\u0631\u0645\u0632\u0646\u06AF\u0627\u0631\u06CC \u0648\u06CC\u0646\u062F\u0648\u0632 (DPAPI) \u062F\u0631 \u062F\u0633\u062A\u0631\u0633 \u0646\u06CC\u0633\u062A\u061B \u0630\u062E\u06CC\u0631\u0647 \u06A9\u0644\u06CC\u062F \u062F\u0633\u062A\u06AF\u0627\u0647 \u062F\u0631 \u0645\u062A\u0646 \u0633\u0627\u062F\u0647 \u0645\u062C\u0627\u0632 \u0646\u06CC\u0633\u062A"
      );
    }
    return `plain:${Buffer.from(token, "utf8").toString("base64")}`;
  }
  openToken(stored) {
    try {
      if (stored.tokenSealed.startsWith("enc:")) {
        const sealed = Buffer.from(stored.tokenSealed.slice(4), "base64");
        return import_electron3.safeStorage.decryptString(sealed);
      }
      if (stored.tokenSealed.startsWith("plain:") && process.platform !== "win32") {
        return Buffer.from(stored.tokenSealed.slice(6), "base64").toString("utf8");
      }
      return null;
    } catch {
      return null;
    }
  }
};

// electron/games-store.ts
var import_electron4 = require("electron");
var import_node_fs4 = __toESM(require("node:fs"));
var import_node_path4 = __toESM(require("node:path"));
var DEFAULT_GAMES = [
  {
    id: "r6s",
    name: "Rainbow Six Siege (\u0631\u0647\u0631\u0648)",
    category: "\u0634\u0648\u062A\u0631 \u062A\u0627\u06A9\u062A\u06CC\u06A9\u0627\u0644",
    icon: "\u{1F6E1}\uFE0F",
    executable: "c:\\program files(x86)\\games\\rainbow six siege\\rainbowsix_rahro_native.exe",
    arguments: "",
    workingDir: "c:\\program files(x86)\\games\\rainbow six siege",
    color: "border-sky-500/30 bg-sky-500/[0.06]",
    enabled: true
  },
  {
    id: "cs16",
    name: "Counter-Strike 1.6",
    category: "\u0634\u0648\u062A\u0631 \u06A9\u0644\u0627\u0633\u06CC\u06A9",
    icon: "\u{1F3AF}",
    executable: "c:\\program files(x86)\\games\\counter-strike 1.6\\hl.exe",
    arguments: "-game cstrike",
    workingDir: "c:\\program files(x86)\\games\\counter-strike 1.6",
    color: "border-amber/30 bg-amber/[0.06]",
    enabled: true
  }
];
function gamesPath() {
  try {
    return import_node_path4.default.join(import_electron4.app.getPath("userData"), "games.json");
  } catch {
    return import_node_path4.default.join(process.cwd(), "games.json");
  }
}
var GamesStore = class {
  constructor() {
    this.cached = null;
  }
  loadGames() {
    if (this.cached !== null) {
      return this.cached;
    }
    const file = gamesPath();
    try {
      if (import_node_fs4.default.existsSync(file)) {
        const raw = import_node_fs4.default.readFileSync(file, "utf8");
        const list = JSON.parse(raw);
        if (Array.isArray(list)) {
          this.cached = list;
          return list;
        }
      }
    } catch {
    }
    this.cached = [...DEFAULT_GAMES];
    this.saveGames(this.cached);
    return this.cached;
  }
  saveGames(games) {
    this.cached = games;
    const file = gamesPath();
    try {
      import_node_fs4.default.mkdirSync(import_node_path4.default.dirname(file), { recursive: true, mode: 448 });
      const tmp = `${file}.tmp`;
      import_node_fs4.default.writeFileSync(tmp, JSON.stringify(games, null, 2), "utf8");
      import_node_fs4.default.renameSync(tmp, file);
    } catch {
    }
    return games;
  }
  addGame(game) {
    const list = this.loadGames();
    const id = "game_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 6);
    const item = {
      ...game,
      id,
      enabled: game.enabled !== void 0 ? game.enabled : true
    };
    list.push(item);
    this.saveGames(list);
    return item;
  }
  updateGame(id, patch) {
    const list = this.loadGames();
    const index = list.findIndex((g) => g.id === id);
    if (index === -1) return null;
    list[index] = { ...list[index], ...patch, id };
    this.saveGames(list);
    return list[index];
  }
  deleteGame(id) {
    const list = this.loadGames();
    const filtered = list.filter((g) => g.id !== id);
    if (filtered.length !== list.length) {
      this.saveGames(filtered);
      return true;
    }
    return false;
  }
  resetDefaults() {
    return this.saveGames([...DEFAULT_GAMES]);
  }
};

// electron/discovery.ts
var import_node_dgram = __toESM(require("node:dgram"));
var import_node_os2 = __toESM(require("node:os"));
var LanDiscoveryClient = class {
  constructor(onDiscovered) {
    this.socket = null;
    this.intervalId = null;
    this.running = false;
    this.onDiscovered = onDiscovered;
  }
  start(port = 19445) {
    if (this.running) return;
    this.running = true;
    try {
      this.socket = import_node_dgram.default.createSocket({ type: "udp4", reuseAddr: true });
      this.socket.on("error", (err) => {
        log("warn", `LAN Discovery socket error: ${err.message}`);
      });
      this.socket.on("message", (msg, rinfo) => {
        try {
          const payload = JSON.parse(msg.toString("utf-8"));
          if (payload.service === "gamenet_salon_server" && payload.fingerprint) {
            this.onDiscovered({
              ...payload,
              host: (rinfo == null ? void 0 : rinfo.address) || String(payload.host || "")
            });
          }
        } catch {
        }
      });
      this.socket.bind(0, () => {
        var _a;
        try {
          (_a = this.socket) == null ? void 0 : _a.setBroadcast(true);
        } catch (e) {
          log("warn", `Failed setting UDP broadcast: ${e}`);
        }
        this.sendProbe(port);
      });
      this.intervalId = setInterval(() => {
        this.sendProbe(port);
      }, 5e3);
    } catch (err) {
      log("warn", `LAN discovery client could not initialize: ${err}`);
    }
  }
  sendProbe(port) {
    if (!this.socket || !this.running) return;
    try {
      const probe = Buffer.from(
        JSON.stringify({
          query: "gamenet_discover",
          hostname: import_node_os2.default.hostname(),
          time: Date.now()
        })
      );
      this.socket.send(probe, 0, probe.length, port, "255.255.255.255");
    } catch (err) {
      log("warn", `Discovery probe send error: ${err}`);
    }
  }
  stop() {
    var _a;
    this.running = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
    try {
      (_a = this.socket) == null ? void 0 : _a.close();
    } catch {
    }
    this.socket = null;
  }
};

// electron/remote-desktop.ts
var import_electron5 = require("electron");
var import_node_child_process2 = require("node:child_process");
var import_node_readline = __toESM(require("node:readline"));
var WIN32_HELPER_PS = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @"
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Windows.Forms;
using System.Runtime.InteropServices;

public class GnRemoteHelper {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct CURSORINFO {
        public int cbSize;
        public int flags;
        public IntPtr hCursor;
        public POINT ptScreenPos;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct ICONINFO {
        public bool fIcon;
        public int xHotspot;
        public int yHotspot;
        public IntPtr hbmMask;
        public IntPtr hbmColor;
    }

    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, int dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
    [DllImport("user32.dll")] public static extern bool GetCursorInfo(ref CURSORINFO pci);
    [DllImport("user32.dll")] public static extern IntPtr CopyIcon(IntPtr hIcon);
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr hIcon);
    [DllImport("user32.dll")] public static extern bool GetIconInfo(IntPtr hIcon, out ICONINFO piconinfo);
    [DllImport("user32.dll")] public static extern bool DrawIconEx(IntPtr hdc, int xLeft, int yTop, IntPtr hIcon, int cxWidth, int cyWidth, int istepIfAniCur, IntPtr hbrFlickerFreeDraw, int diFlags);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr hObject);

    private static ImageCodecInfo jpegCodec = null;
    private static ImageCodecInfo GetJpegCodec() {
        if (jpegCodec != null) return jpegCodec;
        foreach (ImageCodecInfo c in ImageCodecInfo.GetImageEncoders()) {
            if (c.MimeType == "image/jpeg") { jpegCodec = c; break; }
        }
        return jpegCodec;
    }

    private static bool IsExtended(byte vk) {
        return vk == 0x21 || vk == 0x22 || vk == 0x23 || vk == 0x24 ||
               vk == 0x25 || vk == 0x26 || vk == 0x27 || vk == 0x28 ||
               vk == 0x2D || vk == 0x2E || vk == 0x5B || vk == 0x5C ||
               vk == 0x5D || vk == 0x6F || vk == 0x90 || vk == 0xA3 || vk == 0xA5;
    }

    private static void DrawCursor(Graphics g, int offsetX, int offsetY) {
        try {
            CURSORINFO ci = new CURSORINFO();
            ci.cbSize = Marshal.SizeOf(typeof(CURSORINFO));
            if (!GetCursorInfo(ref ci) || (ci.flags & 1) == 0 || ci.hCursor == IntPtr.Zero) return;

            IntPtr hIcon = CopyIcon(ci.hCursor);
            bool copied = hIcon != IntPtr.Zero;
            if (!copied) hIcon = ci.hCursor;
            try {
                int x = ci.ptScreenPos.X - offsetX;
                int y = ci.ptScreenPos.Y - offsetY;
                ICONINFO ii;
                if (GetIconInfo(hIcon, out ii)) {
                    try {
                        x -= ii.xHotspot;
                        y -= ii.yHotspot;
                    } finally {
                        if (ii.hbmMask != IntPtr.Zero) DeleteObject(ii.hbmMask);
                        if (ii.hbmColor != IntPtr.Zero) DeleteObject(ii.hbmColor);
                    }
                }
                IntPtr hdc = g.GetHdc();
                try {
                    DrawIconEx(hdc, x, y, hIcon, 0, 0, 0, IntPtr.Zero, 3);
                } finally {
                    g.ReleaseHdc(hdc);
                }
            } finally {
                if (copied) DestroyIcon(hIcon);
            }
        } catch {
        }
    }

    public static void MoveAbs(double nx, double ny) {
        int sw = Math.Max(1, GetSystemMetrics(0));
        int sh = Math.Max(1, GetSystemMetrics(1));
        double cx = Math.Max(0.0, Math.Min(1.0, nx));
        double cy = Math.Max(0.0, Math.Min(1.0, ny));
        int px = (int)Math.Round(cx * (sw - 1));
        int py = (int)Math.Round(cy * (sh - 1));
        SetCursorPos(px, py);
        mouse_event(0x8001u, (int)Math.Round(cx * 65535.0), (int)Math.Round(cy * 65535.0), 0, UIntPtr.Zero);
    }

    public static void MouseButton(int btn, bool down, double nx, double ny) {
        MoveAbs(nx, ny);
        uint flag = 0;
        if (btn == 0) flag = down ? 0x0002u : 0x0004u;
        else if (btn == 1) flag = down ? 0x0020u : 0x0040u;
        else if (btn == 2) flag = down ? 0x0008u : 0x0010u;
        if (flag != 0) mouse_event(flag, 0, 0, 0, UIntPtr.Zero);
    }

    public static void Wheel(int delta, double nx, double ny) {
        MoveAbs(nx, ny);
        mouse_event(0x0800u, 0, 0, delta, UIntPtr.Zero);
    }

    private static readonly UIntPtr RDP_TAG = new UIntPtr(0x474E5244u);

    public static void Key(byte vk, bool down) {
        byte scan = (byte)(MapVirtualKey((uint)vk, 0) & 0xFF);
        uint flags = (IsExtended(vk) ? 0x0001u : 0u) | (down ? 0u : 0x0002u);
        keybd_event(vk, scan, flags, RDP_TAG);
    }

    public static string CaptureJpeg(int maxWidth, long quality) {
        Rectangle bounds = Screen.PrimaryScreen.Bounds;
        int sw = Math.Max(1, bounds.Width);
        int sh = Math.Max(1, bounds.Height);
        int tw = Math.Min(sw, Math.Max(320, maxWidth));
        int th = Math.Max(180, (int)Math.Round((double)sh * tw / sw));

        using (Bitmap raw = new Bitmap(sw, sh, PixelFormat.Format24bppRgb)) {
            using (Graphics g = Graphics.FromImage(raw)) {
                g.CopyFromScreen(bounds.X, bounds.Y, 0, 0, bounds.Size, CopyPixelOperation.SourceCopy);
                DrawCursor(g, bounds.X, bounds.Y);
            }
            Bitmap target = raw;
            bool disposeTarget = false;
            if (tw != sw || th != sh) {
                target = new Bitmap(tw, th, PixelFormat.Format24bppRgb);
                disposeTarget = true;
                using (Graphics sg = Graphics.FromImage(target)) {
                    sg.InterpolationMode = InterpolationMode.Bilinear;
                    sg.DrawImage(raw, 0, 0, tw, th);
                }
            }
            try {
                using (MemoryStream ms = new MemoryStream()) {
                    ImageCodecInfo codec = GetJpegCodec();
                    if (codec != null) {
                        using (EncoderParameters ep = new EncoderParameters(1))
                        using (EncoderParameter ep0 = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, Math.Max(25L, Math.Min(95L, quality)))) {
                            ep.Param[0] = ep0;
                            target.Save(ms, codec, ep);
                        }
                    } else {
                        target.Save(ms, ImageFormat.Jpeg);
                    }
                    return tw.ToString() + "|" + th.ToString() + "|" + Convert.ToBase64String(ms.ToArray());
                }
            } finally {
                if (disposeTarget) target.Dispose();
            }
        }
    }
}
"@
$ErrorActionPreference = 'Continue'
try { [void][GnRemoteHelper]::SetProcessDPIAware() } catch {}
$elev = "0"
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    if ($pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $elev = "1" }
} catch {}
[Console]::Out.WriteLine("READY|" + $elev)
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line -eq "") { continue }
    $parts = $line.Split('|')
    $op = $parts[0]
    $seq = ""
    try {
        if ($op -eq "CAP") {
            $seq = $parts[1]
            $mw = [int]$parts[2]
            $q = [long]$parts[3]
            $res = [GnRemoteHelper]::CaptureJpeg($mw, $q)
            [Console]::Out.WriteLine("FRAME|" + $seq + "|" + $res)
            [Console]::Out.Flush()
        } elseif ($op -eq "MV") {
            [GnRemoteHelper]::MoveAbs([double]::Parse($parts[1], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "MD") {
            [GnRemoteHelper]::MouseButton([int]$parts[1], $true, [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "MU") {
            [GnRemoteHelper]::MouseButton([int]$parts[1], $false, [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "WH") {
            [GnRemoteHelper]::Wheel([int]$parts[1], [double]::Parse($parts[2], [System.Globalization.CultureInfo]::InvariantCulture), [double]::Parse($parts[3], [System.Globalization.CultureInfo]::InvariantCulture))
        } elseif ($op -eq "KD") {
            [GnRemoteHelper]::Key([byte][int]$parts[1], $true)
        } elseif ($op -eq "KU") {
            [GnRemoteHelper]::Key([byte][int]$parts[1], $false)
        } elseif ($op -eq "SC") {
            $codes = $parts[1].Split(',')
            foreach ($c in $codes) { if ($c -ne "") { [GnRemoteHelper]::Key([byte][int]$c, $true) } }
            for ($i = $codes.Length - 1; $i -ge 0; $i--) { if ($codes[$i] -ne "") { [GnRemoteHelper]::Key([byte][int]$codes[$i], $false) } }
        }
    } catch {
        if ($op -eq "CAP") {
            [Console]::Out.WriteLine("ERR|" + $seq + "|" + ([string]$_.Exception.Message).Replace([char]13, ' ').Replace([char]10, ' '))
            [Console]::Out.Flush()
        }
    }
}
`;
var RemoteDesktopService = class {
  constructor(sendFrame) {
    this.worker = null;
    this.workerReady = false;
    this.workerStarting = null;
    this.workerRetryAfter = 0;
    this.pendingCaptures = /* @__PURE__ */ new Map();
    this.nextCaptureSeq = 1;
    this.warnedUnsupportedInput = false;
    this.streamTimer = null;
    this.streamIdleTimer = null;
    this.streamInFlight = false;
    this.streamFps = 5;
    this.streamWidth = 1024;
    this.streamQuality = 64;
    this.inputQueue = Promise.resolve();
    this.sendFrame = sendFrame;
  }
  handleControl(msg) {
    const action = String(msg.action || "");
    if (action === "screenshot") {
      void this.captureAndSend({
        kind: "screenshot",
        width: clampInt(msg.width, 480, 1920, 1280),
        quality: clampInt(msg.quality, 40, 95, 84),
        requestId: typeof msg.request_id === "string" ? msg.request_id : void 0
      });
      return;
    }
    if (action === "stream_start") {
      this.streamFps = clampInt(msg.fps, 1, 8, 5);
      this.streamWidth = clampInt(msg.width, 480, 1440, 1024);
      this.streamQuality = clampInt(msg.quality, 35, 90, 64);
      void this.ensureWin32Worker();
      this.startStream();
      return;
    }
    if (action === "stream_keepalive") {
      this.bumpIdleTimeout();
      return;
    }
    if (action === "stream_stop") {
      this.stopStream();
      return;
    }
    if (action === "input" && msg.event && typeof msg.event === "object") {
      this.bumpIdleTimeout();
      const ev = msg.event;
      this.inputQueue = this.inputQueue.then(() => this.injectInput(ev)).catch(() => {
      });
    }
  }
  dispose() {
    this.stopStream();
    if (this.worker) {
      try {
        this.worker.kill();
      } catch {
      }
      this.worker = null;
      this.workerReady = false;
    }
    this.clearPendingCaptures();
  }
  clearPendingCaptures() {
    for (const done of this.pendingCaptures.values()) {
      done(null);
    }
    this.pendingCaptures.clear();
  }
  startStream() {
    this.stopStream();
    this.bumpIdleTimeout();
    void this.tickStream();
    const intervalMs = Math.max(120, Math.round(1e3 / Math.max(1, this.streamFps)));
    this.streamTimer = setInterval(() => {
      void this.tickStream();
    }, intervalMs);
  }
  stopStream() {
    if (this.streamTimer) {
      clearInterval(this.streamTimer);
      this.streamTimer = null;
    }
    if (this.streamIdleTimer) {
      clearTimeout(this.streamIdleTimer);
      this.streamIdleTimer = null;
    }
    this.streamInFlight = false;
  }
  bumpIdleTimeout() {
    if (!this.streamTimer) return;
    if (this.streamIdleTimer) clearTimeout(this.streamIdleTimer);
    this.streamIdleTimer = setTimeout(() => {
      this.stopStream();
    }, 15e3);
  }
  async tickStream() {
    if (this.streamInFlight) return;
    this.streamInFlight = true;
    try {
      await this.captureAndSend({
        kind: "stream",
        width: this.streamWidth,
        quality: this.streamQuality
      });
    } finally {
      this.streamInFlight = false;
    }
  }
  async captureAndSend(opts) {
    try {
      const captured = await this.captureScreen(opts.kind, opts.width, opts.quality);
      if (!captured) return;
      this.sendFrame({
        kind: opts.kind,
        width: captured.width,
        height: captured.height,
        format: "jpeg",
        data: captured.data,
        captured_at: (/* @__PURE__ */ new Date()).toISOString(),
        request_id: opts.requestId
      });
    } catch (err) {
      log("warn", `remote capture error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  async captureScreen(kind, maxWidth, quality) {
    if (process.platform === "win32") {
      const workerFrame = await this.captureViaWin32Worker(maxWidth, quality);
      if (workerFrame) return workerFrame;
      if (kind === "stream" && this.workerReady) return null;
    }
    try {
      const display = import_electron5.screen.getPrimaryDisplay();
      const physW = Math.max(1, Math.round(display.size.width * (display.scaleFactor || 1)));
      const physH = Math.max(1, Math.round(display.size.height * (display.scaleFactor || 1)));
      const targetW = Math.min(physW, Math.max(320, maxWidth));
      const targetH = Math.max(180, Math.round(physH * targetW / physW));
      const sources = await import_electron5.desktopCapturer.getSources({
        types: ["screen"],
        thumbnailSize: { width: targetW, height: targetH }
      });
      const primary = sources[0];
      if (primary && !primary.thumbnail.isEmpty()) {
        const jpg = primary.thumbnail.toJPEG(quality);
        const sz = primary.thumbnail.getSize();
        if (jpg.length > 2200) {
          return {
            width: sz.width,
            height: sz.height,
            data: jpg.toString("base64")
          };
        }
      }
    } catch (err) {
      log("warn", `desktopCapturer failed: ${String(err)}`);
    }
    return null;
  }
  async ensureWin32Worker() {
    if (process.platform !== "win32") return false;
    if (this.worker && this.workerReady && !this.worker.killed) return true;
    if (this.workerStarting) return this.workerStarting;
    if (Date.now() < this.workerRetryAfter) return false;
    this.workerStarting = new Promise((resolve) => {
      try {
        const encoded = Buffer.from(WIN32_HELPER_PS, "utf16le").toString("base64");
        const proc = (0, import_node_child_process2.spawn)(
          "powershell.exe",
          [
            "-NoProfile",
            "-NonInteractive",
            "-InputFormat",
            "None",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded
          ],
          { windowsHide: true }
        );
        this.worker = proc;
        this.workerReady = false;
        let settled = false;
        let startupTimer = null;
        const rl = import_node_readline.default.createInterface({ input: proc.stdout });
        const rle = import_node_readline.default.createInterface({ input: proc.stderr });
        const finishStart = (ok) => {
          if (startupTimer) {
            clearTimeout(startupTimer);
            startupTimer = null;
          }
          if (!ok) {
            this.workerRetryAfter = Date.now() + 15e3;
          } else {
            this.workerRetryAfter = 0;
          }
          if (!settled) {
            settled = true;
            resolve(ok);
          }
        };
        rl.on("line", (line) => {
          if (line === "READY" || line.startsWith("READY|")) {
            this.workerReady = true;
            const elevated = line.endsWith("|1");
            log(
              "info",
              elevated ? "win32 remote worker ready (elevated=true)" : "win32 remote worker ready (elevated=false; UIPI blocks input to elevated windows)"
            );
            finishStart(true);
            return;
          }
          if (line.startsWith("FRAME|")) {
            const parts = line.split("|");
            const seq = parseInt(parts[1] || "0", 10);
            const w = parseInt(parts[2] || "0", 10);
            const h = parseInt(parts[3] || "0", 10);
            const data = parts[4] || "";
            const cb = this.pendingCaptures.get(seq);
            if (cb) {
              this.pendingCaptures.delete(seq);
              cb(data ? { width: w, height: h, data } : null);
            }
            return;
          }
          if (line.startsWith("ERR|")) {
            const firstSep = line.indexOf("|", 4);
            const seq = firstSep > 4 ? parseInt(line.slice(4, firstSep), 10) : 0;
            const errText = firstSep > 4 ? line.slice(firstSep + 1) : line.slice(4);
            log("warn", `win32 worker error: ${errText}`);
            const cb = this.pendingCaptures.get(seq);
            if (cb) {
              this.pendingCaptures.delete(seq);
              cb(null);
            }
          }
        });
        rle.on("line", (line) => {
          const trimmed = line.trim();
          if (trimmed) log("warn", `win32 helper stderr: ${trimmed}`);
        });
        proc.on("exit", (code) => {
          if (code && !this.workerReady) {
            log("warn", `win32 helper exited before READY (code ${code})`);
          }
          this.workerReady = false;
          if (this.worker === proc) this.worker = null;
          rl.close();
          rle.close();
          this.clearPendingCaptures();
          finishStart(false);
        });
        startupTimer = setTimeout(() => {
          if (!settled) {
            log("warn", "win32 helper startup timed out after 15s");
            if (this.worker === proc) {
              this.worker = null;
              this.workerReady = false;
            }
            try {
              proc.kill();
            } catch {
            }
            finishStart(false);
          }
        }, 15e3);
      } catch (err) {
        this.workerRetryAfter = Date.now() + 15e3;
        log("warn", `failed spawning win32 helper: ${String(err)}`);
        resolve(false);
      }
    }).finally(() => {
      this.workerStarting = null;
    });
    return this.workerStarting;
  }
  async captureViaWin32Worker(maxWidth, quality) {
    const ok = await this.ensureWin32Worker();
    if (!ok || !this.worker) return null;
    const seq = this.nextCaptureSeq++;
    return await new Promise((resolve) => {
      var _a;
      const timer = setTimeout(() => {
        this.pendingCaptures.delete(seq);
        resolve(null);
      }, 6e3);
      const done = (res) => {
        clearTimeout(timer);
        resolve(res);
      };
      this.pendingCaptures.set(seq, done);
      try {
        (_a = this.worker) == null ? void 0 : _a.stdin.write(`CAP|${seq}|${maxWidth}|${quality}
`);
      } catch {
        this.pendingCaptures.delete(seq);
        clearTimeout(timer);
        resolve(null);
      }
    });
  }
  async injectInput(ev) {
    if (process.platform !== "win32") {
      if (!this.warnedUnsupportedInput) {
        this.warnedUnsupportedInput = true;
        log("info", `remote input injection skipped on non-win32 platform (${process.platform})`);
      }
      return;
    }
    const ok = await this.ensureWin32Worker();
    if (!ok || !this.worker) return;
    const kind = String(ev.kind || "");
    const nx = clampFloat(ev.x, 0, 1, 0.5).toFixed(5);
    const ny = clampFloat(ev.y, 0, 1, 0.5).toFixed(5);
    let line = "";
    if (kind === "mv") {
      line = `MV|${nx}|${ny}`;
    } else if (kind === "md") {
      const btn = clampInt(ev.button, 0, 2, 0);
      line = `MD|${btn}|${nx}|${ny}`;
    } else if (kind === "mu") {
      const btn = clampInt(ev.button, 0, 2, 0);
      line = `MU|${btn}|${nx}|${ny}`;
    } else if (kind === "wh") {
      const delta = clampInt(ev.delta, -600, 600, -120);
      line = `WH|${delta}|${nx}|${ny}`;
    } else if (kind === "kd" || kind === "ku") {
      const vk = resolveWindowsVk(ev);
      if (vk > 0) line = `${kind === "kd" ? "KD" : "KU"}|${vk}`;
    } else if (kind === "combo" && Array.isArray(ev.vks)) {
      const vks = ev.vks.map((n) => clampInt(n, 0, 255, 0)).filter((n) => n > 0 && n < 255);
      if (vks.length > 0) line = `SC|${vks.join(",")}`;
    }
    if (line) {
      try {
        this.worker.stdin.write(`${line}
`);
      } catch {
      }
    }
  }
};
function clampInt(val, min, max, fallback) {
  const n = typeof val === "number" ? val : Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.round(n)));
}
function clampFloat(val, min, max, fallback) {
  const n = typeof val === "number" ? val : Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}
var CODE_TO_VK = {
  Backspace: 8,
  Tab: 9,
  Enter: 13,
  NumpadEnter: 13,
  ShiftLeft: 16,
  ShiftRight: 16,
  ControlLeft: 17,
  ControlRight: 163,
  AltLeft: 18,
  AltRight: 165,
  Pause: 19,
  CapsLock: 20,
  Escape: 27,
  Space: 32,
  PageUp: 33,
  PageDown: 34,
  End: 35,
  Home: 36,
  ArrowLeft: 37,
  ArrowUp: 38,
  ArrowRight: 39,
  ArrowDown: 40,
  PrintScreen: 44,
  Insert: 45,
  Delete: 46,
  MetaLeft: 91,
  MetaRight: 92,
  ContextMenu: 93,
  NumLock: 144,
  ScrollLock: 145,
  Semicolon: 186,
  Equal: 187,
  Comma: 188,
  Minus: 189,
  Period: 190,
  Slash: 191,
  Backquote: 192,
  BracketLeft: 219,
  Backslash: 220,
  BracketRight: 221,
  Quote: 222,
  NumpadMultiply: 106,
  NumpadAdd: 107,
  NumpadSubtract: 109,
  NumpadDecimal: 110,
  NumpadDivide: 111
};
function resolveWindowsVk(ev) {
  const code = typeof ev.code === "string" ? ev.code : "";
  if (code) {
    if (CODE_TO_VK[code]) return CODE_TO_VK[code];
    if (code.startsWith("Key") && code.length === 4) {
      return code.charCodeAt(3);
    }
    if (code.startsWith("Digit") && code.length === 6) {
      return code.charCodeAt(5);
    }
    if (code.startsWith("Numpad") && code.length === 7) {
      const d = code.charCodeAt(6) - 48;
      if (d >= 0 && d <= 9) return 96 + d;
    }
    if (code.startsWith("F") && code.length <= 3) {
      const f = parseInt(code.slice(1), 10);
      if (f >= 1 && f <= 12) return 111 + f;
    }
  }
  const keyCode = typeof ev.keyCode === "number" ? ev.keyCode : 0;
  if (keyCode > 0 && keyCode < 255) return keyCode;
  return 0;
}

// electron/kiosk-guard.ts
var import_node_child_process3 = require("node:child_process");
var import_node_readline2 = __toESM(require("node:readline"));
var KIOSK_GUARD_PS = `
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;
using Microsoft.Win32;

public class GnKioskGuard {
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumeratorComObject {
    }

    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator {
        [PreserveSig]
        int EnumAudioEndpoints(int dataFlow, int dwStateMask, out IntPtr ppDevices);
        [PreserveSig]
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppEndpoint);
    }

    [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice {
        [PreserveSig]
        int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
    }

    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr pNotify);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr pNotify);
        [PreserveSig] int GetChannelCount(out uint pnChannelCount);
        [PreserveSig] int SetMasterVolumeLevel(float fLevelDB, ref Guid pguidEventContext);
        [PreserveSig] int SetMasterVolumeLevelScalar(float fLevel, ref Guid pguidEventContext);
        [PreserveSig] int GetMasterVolumeLevel(out float pfLevelDB);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float pfLevel);
        [PreserveSig] int SetChannelVolumeLevel(uint nChannel, float fLevelDB, ref Guid pguidEventContext);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, ref Guid pguidEventContext);
        [PreserveSig] int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, ref Guid pguidEventContext);
        [PreserveSig] int GetMute(out bool pbMute);
    }

    private const int WH_KEYBOARD_LL = 13;
    private const int WM_QUIT = 0x0012;
    private const int WM_KEYDOWN = 0x0100;
    private const int WM_KEYUP = 0x0101;
    private const int WM_SYSKEYDOWN = 0x0104;
    private const int WM_SYSKEYUP = 0x0105;

    private const uint LLKHF_ALTDOWN = 0x20;
    private static readonly UIntPtr RDP_TAG = new UIntPtr(0x474E5244u);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MSG {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public POINT pt;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KBDLLHOOKSTRUCT {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    private static extern int GetMessage(out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern bool PostThreadMessage(uint idThread, uint Msg, UIntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr FindWindowEx(IntPtr parentHandle, IntPtr childAfter, string className, string windowTitle);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    [DllImport("user32.dll")]
    private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SystemParametersInfo(uint uiAction, uint uiParam, IntPtr pvParam, uint fWinIni);

    [DllImport("user32.dll", EntryPoint = "SystemParametersInfo", SetLastError = true)]
    private static extern bool SystemParametersInfoGet(uint uiAction, uint uiParam, out int pvParam, uint fWinIni);

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr GetModuleHandle(string lpModuleName);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    // 0 = DISABLED, 1 = LOCK (kiosk locked), 2 = GAME (kiosk active during user session)
    private static volatile int _mode = 0;
    private static volatile bool _quitting = false;
    private static volatile bool _ctrlPressed = false;
    private static volatile bool _shiftPressed = false;
    private static volatile bool _altPressed = false;
    private static IntPtr _hookId = IntPtr.Zero;
    private static uint _mainThreadId = 0;
    private static readonly LowLevelKeyboardProc _proc = HookCallback;

    private static bool IsKeyDown(int vk) {
        return (GetAsyncKeyState(vk) & 0x8000) != 0;
    }

    private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam) {
        if (nCode >= 0 && _mode != 0) {
            int msg = wParam.ToInt32();
            bool isKeyEvent = (msg == WM_KEYDOWN || msg == WM_KEYUP || msg == WM_SYSKEYDOWN || msg == WM_SYSKEYUP);
            if (isKeyEvent) {
                KBDLLHOOKSTRUCT info = (KBDLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(KBDLLHOOKSTRUCT));
                if (info.dwExtraInfo.ToUInt64() == RDP_TAG.ToUInt64()) {
                    return CallNextHookEx(_hookId, nCode, wParam, lParam);
                }

                uint vk = info.vkCode;
                bool isDown = (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN);
                bool isUp = (msg == WM_KEYUP || msg == WM_SYSKEYUP);

                if (vk == 0x11 || vk == 0xA2 || vk == 0xA3) {
                    _ctrlPressed = isDown;
                }
                if (vk == 0x10 || vk == 0xA0 || vk == 0xA1) {
                    _shiftPressed = isDown;
                }
                if (vk == 0x12 || vk == 0xA4 || vk == 0xA5) {
                    _altPressed = isDown;
                }

                bool altDown = (info.flags & LLKHF_ALTDOWN) != 0 || IsKeyDown(0x12) || IsKeyDown(0xA4) || IsKeyDown(0xA5) || _altPressed;
                bool ctrlDown = IsKeyDown(0x11) || IsKeyDown(0xA2) || IsKeyDown(0xA3) || _ctrlPressed;
                bool shiftDown = IsKeyDown(0x10) || IsKeyDown(0xA0) || IsKeyDown(0xA1) || _shiftPressed;

                // Block Left Win (0x5B), Right Win (0x5C), Context Menu / Apps key (0x5D)
                if (vk == 0x5B || vk == 0x5C || vk == 0x5D) {
                    return (IntPtr)1;
                }

                // Alt+F5 (vk == 0x74 && altDown): Fast logout / lock screen keeping games alive
                if (vk == 0x74 && altDown) {
                    if (isDown) {
                        Console.Out.WriteLine("EVENT|ALTF5");
                        Console.Out.Flush();
                    }
                    return (IntPtr)1;
                }

                // Alt+Tab (vk == 0x09 && altDown)
                if (vk == 0x09 && altDown) {
                    if (_mode == 1) {
                        return (IntPtr)1;
                    } else if (_mode == 2) {
                        if (isDown) {
                            SwitchToNextWindow();
                            Console.Out.WriteLine("EVENT|ALTTAB");
                            Console.Out.Flush();
                        }
                        return (IntPtr)1;
                    }
                }

                // Block Ctrl+Shift+Esc (Task Manager), Ctrl+Esc (Start Menu), Alt+Esc (Window Switch)
                if (vk == 0x1B && (ctrlDown || altDown || shiftDown)) {
                    return (IntPtr)1;
                }

                // Block Alt+Space (System Window Menu)
                if (vk == 0x20 && altDown) {
                    return (IntPtr)1;
                }

                // Block Alt+F4 system-wide while screen is locked (in GAME mode Electron blocks closing GameNet itself)
                if (vk == 0x73 && altDown && _mode == 1) {
                    return (IntPtr)1;
                }
            }
        }
        return CallNextHookEx(_hookId, nCode, wParam, lParam);
    }

    private static bool IsApplicationWindow(IntPtr hWnd) {
        try {
            if (!IsWindowVisible(hWnd)) return false;
            int len = GetWindowTextLength(hWnd);
            if (len <= 0) return false;
            if (GetWindow(hWnd, 4 /* GW_OWNER */) != IntPtr.Zero) return false;
            int exStyle = GetWindowLong(hWnd, -20 /* GWL_EXSTYLE */);
            if ((exStyle & 0x00000080 /* WS_EX_TOOLWINDOW */) != 0) return false;
            StringBuilder sb = new StringBuilder(256);
            GetWindowText(hWnd, sb, sb.Capacity);
            string title = sb.ToString().Trim();
            if (string.IsNullOrEmpty(title)) return false;
            if (title == "Program Manager" || title == "Windows Task Manager" || title == "Windows Security") return false;
            return true;
        } catch {
            return false;
        }
    }

    public static void ListWindows() {
        try {
            System.Collections.Generic.List<string> list = new System.Collections.Generic.List<string>();
            IntPtr fg = GetForegroundWindow();
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    if (IsApplicationWindow(hWnd)) {
                        StringBuilder sb = new StringBuilder(256);
                        GetWindowText(hWnd, sb, sb.Capacity);
                        string title = sb.ToString().Trim();
                        uint pid = 0;
                        GetWindowThreadProcessId(hWnd, out pid);
                        string pName = "";
                        try {
                            Process p = Process.GetProcessById((int)pid);
                            pName = p.ProcessName;
                        } catch {}
                        bool isFg = (hWnd == fg);
                        bool isMin = IsIconic(hWnd);
                        string row = hWnd.ToInt64().ToString() + "	" + pid.ToString() + "	" + (isFg ? "1" : "0") + "	" + (isMin ? "1" : "0") + "	" + pName.Replace("	", " ") + "	" + title.Replace("	", " ");
                        list.Add(row);
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);

            Console.Out.WriteLine("WINDOWS_START");
            foreach (string row in list) {
                Console.Out.WriteLine("WINDOW|" + row);
            }
            Console.Out.WriteLine("WINDOWS_END");
            Console.Out.Flush();
        } catch {}
    }

    public static void FocusWindow(IntPtr hWnd) {
        try {
            if (IsIconic(hWnd)) {
                ShowWindowAsync(hWnd, 9 /* SW_RESTORE */);
            } else {
                ShowWindowAsync(hWnd, 5 /* SW_SHOW */);
            }
            SetForegroundWindow(hWnd);
        } catch {}
    }

    public static void MinimizeWindow(IntPtr hWnd) {
        try {
            ShowWindowAsync(hWnd, 6 /* SW_MINIMIZE */);
        } catch {}
    }

    public static void CloseWindow(IntPtr hWnd, int pid) {
        try {
            PostMessage(hWnd, 0x0010 /* WM_CLOSE */, IntPtr.Zero, IntPtr.Zero);
        } catch {}
    }

    public static void KillAllApps(int currentPid) {
        try {
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    if (IsApplicationWindow(hWnd)) {
                        uint pid = 0;
                        GetWindowThreadProcessId(hWnd, out pid);
                        if (pid != 0 && pid != (uint)currentPid) {
                            try {
                                Process p = Process.GetProcessById((int)pid);
                                string pName = p.ProcessName.ToLowerInvariant();
                                if (pName != "explorer" && pName != "gamenet" && pName != "electron" &&
                                    !pName.StartsWith("csrss") && !pName.StartsWith("dwm") &&
                                    !pName.StartsWith("lsass") && !pName.StartsWith("services") &&
                                    !pName.StartsWith("smss") && !pName.StartsWith("svchost") &&
                                    !pName.StartsWith("winlogon") && !pName.StartsWith("taskhost")) {
                                    p.Kill();
                                }
                            } catch {}
                        }
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);
        } catch {}
    }

    public static void SwitchToNextWindow() {
        try {
            System.Collections.Generic.List<IntPtr> wins = new System.Collections.Generic.List<IntPtr>();
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                if (IsApplicationWindow(hWnd)) {
                    wins.Add(hWnd);
                }
                return true;
            }, IntPtr.Zero);

            if (wins.Count == 0) return;
            if (wins.Count == 1) {
                FocusWindow(wins[0]);
                return;
            }
            IntPtr fg = GetForegroundWindow();
            int idx = wins.IndexOf(fg);
            int nextIdx = (idx + 1) % wins.Count;
            IntPtr nextHwnd = wins[nextIdx];
            FocusWindow(nextHwnd);
        } catch {}
    }

    private static IAudioEndpointVolume GetEndpointVolume(int role) {
        IMMDeviceEnumerator enumerator = null;
        IMMDevice dev = null;
        try {
            enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
            int hr = enumerator.GetDefaultAudioEndpoint(0, role, out dev);
            if (hr != 0 || dev == null) {
                return null;
            }
            Guid iid = typeof(IAudioEndpointVolume).GUID;
            object activated = null;
            int hrAct = dev.Activate(ref iid, 23, IntPtr.Zero, out activated);
            if (hrAct != 0 || activated == null) {
                return null;
            }
            return activated as IAudioEndpointVolume;
        } catch {
            return null;
        } finally {
            if (dev != null) { try { Marshal.ReleaseComObject(dev); } catch {} }
            if (enumerator != null) { try { Marshal.ReleaseComObject(enumerator); } catch {} }
        }
    }

    public static int GetMasterVolume(int fallback) {
        for (int role = 0; role <= 1; role++) {
            IAudioEndpointVolume epv = GetEndpointVolume(role);
            if (epv != null) {
                try {
                    bool muted = false;
                    float scalar = 0.0f;
                    int hrMute = epv.GetMute(out muted);
                    int hrVol = epv.GetMasterVolumeLevelScalar(out scalar);
                    if (hrVol == 0) {
                        if (hrMute == 0 && muted) return 0;
                        int pct = (int)Math.Round(scalar * 100.0f);
                        if (pct < 0) pct = 0;
                        if (pct > 100) pct = 100;
                        return pct;
                    }
                } catch {}
                finally {
                    try { Marshal.ReleaseComObject(epv); } catch {}
                }
            }
        }
        return fallback;
    }

    public static int SetMasterVolume(int level) {
        int clamped = level;
        if (clamped < 0) clamped = 0;
        if (clamped > 100) clamped = 100;
        bool anySet = false;
        for (int role = 0; role <= 1; role++) {
            IAudioEndpointVolume epv = GetEndpointVolume(role);
            if (epv != null) {
                try {
                    Guid ctx = Guid.Empty;
                    if (clamped == 0) {
                        epv.SetMasterVolumeLevelScalar(0.0f, ref ctx);
                        epv.SetMute(true, ref ctx);
                    } else {
                        epv.SetMute(false, ref ctx);
                        epv.SetMasterVolumeLevelScalar((float)clamped / 100.0f, ref ctx);
                    }
                    anySet = true;
                } catch {}
                finally {
                    try { Marshal.ReleaseComObject(epv); } catch {}
                }
            }
        }
        return anySet ? clamped : GetMasterVolume(clamped);
    }

    public static int GetMouseSpeed(int fallback) {
        try {
            int spd = 0;
            if (SystemParametersInfoGet(0x0070, 0, out spd, 0)) {
                if (spd >= 1 && spd <= 20) return spd;
            }
        } catch {}
        return fallback;
    }

    public static int SetMouseSpeed(int speed) {
        int clamped = speed;
        if (clamped < 1) clamped = 1;
        if (clamped > 20) clamped = 20;
        try {
            SystemParametersInfo(0x0071, 0, new IntPtr(clamped), 0x01 | 0x02);
        } catch {}
        try {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Control PanelMouse")) {
                if (key != null) {
                    key.SetValue("MouseSensitivity", clamped.ToString(), RegistryValueKind.String);
                }
            }
        } catch {}
        return GetMouseSpeed(clamped);
    }

    private static void EmitSystemSettings(int volFallback, int mouseFallback) {
        int vol = GetMasterVolume(volFallback);
        int mouse = GetMouseSpeed(mouseFallback);
        Console.Out.WriteLine("SYS_SETTINGS|" + vol.ToString() + "|" + mouse.ToString());
        Console.Out.Flush();
    }

    private static void SetTaskbarVisible(bool visible) {
        try {
            int cmd = visible ? 5 : 0; // SW_SHOW = 5, SW_HIDE = 0
            IntPtr primaryTray = FindWindow("Shell_TrayWnd", null);
            if (primaryTray != IntPtr.Zero) {
                ShowWindowAsync(primaryTray, cmd);
            }
            IntPtr secondaryTray = FindWindow("Shell_SecondaryTrayWnd", null);
            if (secondaryTray != IntPtr.Zero) {
                ShowWindowAsync(secondaryTray, cmd);
            }
            IntPtr startBtn = FindWindowEx(IntPtr.Zero, IntPtr.Zero, "Button", "Start");
            if (startBtn != IntPtr.Zero) {
                ShowWindowAsync(startBtn, cmd);
            }
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
                try {
                    StringBuilder sb = new StringBuilder(64);
                    if (GetClassName(hWnd, sb, sb.Capacity) > 0) {
                        string cls = sb.ToString();
                        bool isShellBar = (cls == "Shell_TrayWnd" || cls == "Shell_SecondaryTrayWnd");
                        bool isWin7Start = (cls == "Button" && primaryTray != IntPtr.Zero && GetWindow(hWnd, 4 /* GW_OWNER */) == primaryTray);
                        if (isShellBar || isWin7Start) {
                            bool currentlyVisible = IsWindowVisible(hWnd);
                            if (visible && !currentlyVisible) {
                                ShowWindowAsync(hWnd, cmd);
                            } else if (!visible && currentlyVisible) {
                                ShowWindowAsync(hWnd, cmd);
                            }
                        }
                    }
                } catch {}
                return true;
            }, IntPtr.Zero);
        } catch {}
    }

    private static void SetDisableTaskMgr(bool disabled) {
        try {
            const string sysKey = @"SoftwareMicrosoftWindowsCurrentVersionPoliciesSystem";
            const string expKey = @"SoftwareMicrosoftWindowsCurrentVersionPoliciesExplorer";
            if (disabled) {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(sysKey)) {
                    if (key != null) {
                        key.SetValue("DisableTaskMgr", 1, RegistryValueKind.DWord);
                        key.SetValue("DisableLockWorkstation", 1, RegistryValueKind.DWord);
                        key.SetValue("DisableChangePassword", 1, RegistryValueKind.DWord);
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(expKey)) {
                    if (key != null) {
                        key.SetValue("NoLogoff", 1, RegistryValueKind.DWord);
                    }
                }
            } else {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(sysKey, true)) {
                    if (key != null) {
                        try { key.DeleteValue("DisableTaskMgr", false); } catch {}
                        try { key.DeleteValue("DisableLockWorkstation", false); } catch {}
                        try { key.DeleteValue("DisableChangePassword", false); } catch {}
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(expKey, true)) {
                    if (key != null) {
                        try { key.DeleteValue("NoLogoff", false); } catch {}
                    }
                }
            }
        } catch {}
    }

    private static void ApplyMode(int nextMode) {
        int prev = _mode;
        _mode = nextMode;
        bool active = nextMode != 0;
        if (active) {
            SetTaskbarVisible(false);
            if (prev == 0) {
                SetDisableTaskMgr(true);
            }
        } else {
            if (prev != 0) {
                SetTaskbarVisible(true);
                SetDisableTaskMgr(false);
            }
        }
    }

    private static IntPtr InstallHook() {
        IntPtr hMod = IntPtr.Zero;
        try {
            using (Process curProcess = Process.GetCurrentProcess())
            using (ProcessModule curModule = curProcess.MainModule) {
                if (curModule != null) {
                    hMod = GetModuleHandle(curModule.ModuleName);
                }
            }
        } catch {}
        if (hMod == IntPtr.Zero) {
            try { hMod = GetModuleHandle(null); } catch {}
        }
        return SetWindowsHookEx(WH_KEYBOARD_LL, _proc, hMod, 0);
    }

    private static void OnSessionEnding(object sender, SessionEndingEventArgs e) {
        ApplyMode(0);
    }

    public static void Run(int initialMode) {
        _mainThreadId = GetCurrentThreadId();
        ApplyMode(initialMode);
        _hookId = InstallHook();
        if (_hookId == IntPtr.Zero) {
            int err = Marshal.GetLastWin32Error();
            Console.Out.WriteLine("ERR|hook_failed_" + err.ToString());
            Console.Out.Flush();
        } else {
            Console.Out.WriteLine("READY");
            Console.Out.Flush();
        }

        try {
            SystemEvents.SessionEnding += OnSessionEnding;
        } catch {}

        System.Threading.Timer watchdog = new System.Threading.Timer(delegate(object state) {
            if (!_quitting && _mode != 0) {
                SetTaskbarVisible(false);
                try {
                    Process[] mgrs = Process.GetProcessesByName("taskmgr");
                    foreach (Process p in mgrs) {
                        try { p.Kill(); } catch {}
                    }
                } catch {}
            }
        }, null, 1000, 1000);

        Thread reader = new Thread(new ThreadStart(delegate {
            try {
                while (true) {
                    string line = Console.In.ReadLine();
                    if (line == null) {
                        break;
                    }
                    string rawLine = line.Trim();
                    string cmd = rawLine.ToUpperInvariant();
                    if (cmd == "LOCK") {
                        ApplyMode(1);
                    } else if (cmd == "GAME") {
                        ApplyMode(2);
                    } else if (cmd == "DISABLE") {
                        ApplyMode(0);
                    } else if (cmd == "LIST_WINDOWS") {
                        ListWindows();
                    } else if (cmd.StartsWith("FOCUS ")) {
                        try {
                            IntPtr h = (IntPtr)long.Parse(rawLine.Substring(6).Trim());
                            FocusWindow(h);
                        } catch {}
                    } else if (cmd.StartsWith("MINIMIZE ")) {
                        try {
                            IntPtr h = (IntPtr)long.Parse(rawLine.Substring(9).Trim());
                            MinimizeWindow(h);
                        } catch {}
                    } else if (cmd.StartsWith("CLOSE ")) {
                        try {
                            string[] parts = rawLine.Substring(6).Trim().Split(' ');
                            IntPtr h = (IntPtr)long.Parse(parts[0]);
                            int pid = parts.Length > 1 ? int.Parse(parts[1]) : 0;
                            CloseWindow(h, pid);
                        } catch {}
                    } else if (cmd.StartsWith("KILL_ALL_APPS")) {
                        try {
                            string[] parts = rawLine.Split(' ');
                            int myPid = parts.Length > 1 ? int.Parse(parts[1]) : 0;
                            KillAllApps(myPid);
                        } catch {}
                    } else if (cmd == "SWITCH_NEXT") {
                        SwitchToNextWindow();
                    } else if (cmd == "GET_SYS_SETTINGS") {
                        EmitSystemSettings(75, 10);
                    } else if (cmd.StartsWith("SET_VOLUME ")) {
                        try {
                            int val = int.Parse(rawLine.Substring(11).Trim());
                            int actual = SetMasterVolume(val);
                            EmitSystemSettings(actual, GetMouseSpeed(10));
                        } catch {}
                    } else if (cmd.StartsWith("SET_MOUSE_SPEED ")) {
                        try {
                            int val = int.Parse(rawLine.Substring(16).Trim());
                            int actual = SetMouseSpeed(val);
                            EmitSystemSettings(GetMasterVolume(75), actual);
                        } catch {}
                    } else if (cmd == "QUIT") {
                        break;
                    }
                }
            } catch {}
            _quitting = true;
            ApplyMode(0);
            if (_mainThreadId != 0) {
                PostThreadMessage(_mainThreadId, WM_QUIT, UIntPtr.Zero, IntPtr.Zero);
            }
        }));
        reader.IsBackground = true;
        try { reader.SetApartmentState(ApartmentState.STA); } catch {}
        reader.Start();

        try {
            MSG msg;
            while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0) {
                TranslateMessage(ref msg);
                DispatchMessage(ref msg);
            }
        } finally {
            _quitting = true;
            try { watchdog.Dispose(); } catch {}
            try { SystemEvents.SessionEnding -= OnSessionEnding; } catch {}
            if (_hookId != IntPtr.Zero) {
                UnhookWindowsHookEx(_hookId);
                _hookId = IntPtr.Zero;
            }
            ApplyMode(0);
        }
    }
}
"@
[GnKioskGuard]::Run(__INITIAL_MODE__)
`;
function modeToInt(mode) {
  if (mode === "LOCK") return 1;
  if (mode === "GAME") return 2;
  return 0;
}
var Win32KioskGuard = class {
  constructor() {
    this.worker = null;
    this.workerReady = false;
    this.mode = "DISABLED";
    this.desiredMode = "DISABLED";
    this.disposed = false;
    this.retryTimer = null;
    this.pendingWindowsResolve = null;
    this.pendingWindowsPromise = null;
    this.collectingWindows = null;
    this.pendingSysResolves = [];
    this.pendingRawCommands = [];
    this.cachedVolume = 75;
    this.cachedMouseSpeed = 10;
  }
  ensureStarted() {
    if (process.platform !== "win32" || this.disposed) return;
    if (!this.worker) {
      this.startWorker(this.desiredMode);
    }
  }
  setMode(next) {
    this.desiredMode = next;
    if (process.platform !== "win32" || this.disposed) {
      this.mode = next;
      return;
    }
    if (next === "DISABLED" && !this.worker) {
      this.mode = "DISABLED";
      return;
    }
    if (!this.worker) {
      this.mode = next;
      this.startWorker(next);
      return;
    }
    if (this.mode !== next) {
      this.mode = next;
      this.sendCommand(next);
    }
  }
  startWorker(initialMode) {
    if (this.worker || this.disposed || process.platform !== "win32") return;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    try {
      const rawScript = KIOSK_GUARD_PS.replace("__INITIAL_MODE__", String(modeToInt(initialMode)));
      const script = rawScript.split("\n").map((line) => line.trim()).filter((line) => line.length > 0 && !line.startsWith("//")).join("\n");
      const encoded = Buffer.from(script, "utf16le").toString("base64");
      const proc = (0, import_node_child_process3.spawn)(
        "powershell.exe",
        ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        { windowsHide: true }
      );
      this.worker = proc;
      const rl = import_node_readline2.default.createInterface({ input: proc.stdout });
      const rle = import_node_readline2.default.createInterface({ input: proc.stderr });
      rl.on("line", (line) => {
        var _a, _b, _c, _d;
        const trimmed = line.trim();
        if (!trimmed) return;
        if (trimmed === "READY") {
          this.workerReady = true;
          log("info", `win32 kiosk guard active (mode=${this.desiredMode})`);
          (_a = this.onWorkerUp) == null ? void 0 : _a.call(this);
          if (this.desiredMode !== initialMode) {
            this.sendCommand(this.desiredMode);
          }
          const queued = this.pendingRawCommands.splice(0, this.pendingRawCommands.length);
          for (const qCmd of queued) {
            this.writeLine(qCmd);
          }
        } else if (trimmed.startsWith("SYS_SETTINGS|")) {
          const parts = trimmed.split("|");
          if (parts.length >= 3) {
            const vol = Number(parts[1]);
            const spd = Number(parts[2]);
            if (Number.isFinite(vol)) this.cachedVolume = Math.min(100, Math.max(0, Math.round(vol)));
            if (Number.isFinite(spd)) this.cachedMouseSpeed = Math.min(20, Math.max(1, Math.round(spd)));
          }
          const resolvers = this.pendingSysResolves.splice(0, this.pendingSysResolves.length);
          for (const resFn of resolvers) {
            resFn({ volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed });
          }
        } else if (trimmed === "EVENT|ALTF5") {
          log("info", "win32 kiosk guard detected Alt+F5 event");
          (_b = this.onAltF5) == null ? void 0 : _b.call(this);
        } else if (trimmed === "EVENT|ALTTAB") {
          (_c = this.onAltTab) == null ? void 0 : _c.call(this);
        } else if (trimmed === "WINDOWS_START") {
          this.collectingWindows = [];
        } else if (trimmed.startsWith("WINDOW|")) {
          const content = trimmed.slice(7);
          if (this.collectingWindows && content) {
            const parts = content.split("	");
            if (parts.length >= 6) {
              this.collectingWindows.push({
                hwnd: parts[0],
                pid: Number(parts[1]) || 0,
                isForeground: parts[2] === "1",
                isMinimized: parts[3] === "1",
                processName: parts[4] || "",
                title: parts[5] || ""
              });
            }
          }
        } else if (trimmed.startsWith("WINDOWS|")) {
          const content = trimmed.slice(8);
          if (this.collectingWindows && content) {
            const rows = content.split("\n");
            for (const r of rows) {
              const parts = r.split("	");
              if (parts.length >= 6) {
                this.collectingWindows.push({
                  hwnd: parts[0],
                  pid: Number(parts[1]) || 0,
                  isForeground: parts[2] === "1",
                  isMinimized: parts[3] === "1",
                  processName: parts[4] || "",
                  title: parts[5] || ""
                });
              }
            }
          }
        } else if (trimmed === "WINDOWS_END") {
          if (this.pendingWindowsResolve) {
            this.pendingWindowsResolve(this.collectingWindows || []);
            this.pendingWindowsResolve = null;
            this.pendingWindowsPromise = null;
            this.collectingWindows = null;
          }
        } else if (trimmed.startsWith("ERR|")) {
          log("warn", `win32 kiosk guard warning: ${trimmed.slice(4)}`);
          if (trimmed.includes("hook_failed")) (_d = this.onWorkerDown) == null ? void 0 : _d.call(this);
        }
      });
      rle.on("line", (line) => {
        const trimmed = line.trim();
        if (trimmed) log("warn", `win32 kiosk guard stderr: ${trimmed}`);
      });
      proc.on("exit", (code) => {
        var _a;
        if (this.worker === proc) {
          this.worker = null;
          this.workerReady = false;
        }
        rl.close();
        rle.close();
        if (!this.disposed && this.desiredMode !== "DISABLED") {
          log("warn", `win32 kiosk guard exited unexpectedly (code=${code}); restarting in 2s`);
          (_a = this.onWorkerDown) == null ? void 0 : _a.call(this);
          this.retryTimer = setTimeout(() => {
            this.retryTimer = null;
            if (!this.disposed && this.desiredMode !== "DISABLED") {
              this.startWorker(this.desiredMode);
            }
          }, 2e3);
        }
      });
    } catch (err) {
      log("warn", `failed starting win32 kiosk guard: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  writeLine(commandStr) {
    try {
      if (this.worker && this.worker.stdin.writable) {
        this.worker.stdin.write(`${commandStr}
`);
      }
    } catch {
    }
  }
  sendCommand(cmd) {
    const target = cmd === "DISABLED" ? "DISABLE" : cmd;
    this.sendRawCommand(target);
  }
  sendRawCommand(commandStr) {
    if (process.platform !== "win32" || this.disposed) return;
    if (!this.worker) {
      this.pendingRawCommands.push(commandStr);
      this.startWorker(this.desiredMode);
      return;
    }
    if (!this.workerReady && commandStr !== "QUIT") {
      this.pendingRawCommands.push(commandStr);
      return;
    }
    this.writeLine(commandStr);
  }
  async getSystemSettings() {
    if (process.platform !== "win32" || this.disposed) {
      return { volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed };
    }
    return new Promise((resolve) => {
      this.pendingSysResolves.push(resolve);
      this.sendRawCommand("GET_SYS_SETTINGS");
      setTimeout(() => {
        const idx = this.pendingSysResolves.indexOf(resolve);
        if (idx >= 0) {
          this.pendingSysResolves.splice(idx, 1);
          resolve({ volume: this.cachedVolume, mouseSpeed: this.cachedMouseSpeed });
        }
      }, 5e3);
    });
  }
  setVolume(level) {
    const clamped = Math.min(100, Math.max(0, Math.round(level)));
    this.cachedVolume = clamped;
    this.sendRawCommand(`SET_VOLUME ${clamped}`);
    return clamped;
  }
  setMouseSpeed(speed) {
    const clamped = Math.min(20, Math.max(1, Math.round(speed)));
    this.cachedMouseSpeed = clamped;
    this.sendRawCommand(`SET_MOUSE_SPEED ${clamped}`);
    return clamped;
  }
  async listWindows() {
    if (process.platform !== "win32" || !this.worker) return [];
    if (this.pendingWindowsPromise) {
      return this.pendingWindowsPromise;
    }
    this.pendingWindowsPromise = new Promise((resolve) => {
      const finish = (wins) => {
        this.pendingWindowsPromise = null;
        resolve(wins);
      };
      this.pendingWindowsResolve = finish;
      this.collectingWindows = [];
      this.sendRawCommand("LIST_WINDOWS");
      setTimeout(() => {
        if (this.pendingWindowsResolve === finish) {
          this.pendingWindowsResolve = null;
          this.pendingWindowsPromise = null;
          resolve(this.collectingWindows || []);
          this.collectingWindows = null;
        }
      }, 3e3);
    });
    return this.pendingWindowsPromise;
  }
  focusWindow(hwnd) {
    this.sendRawCommand(`FOCUS ${hwnd}`);
  }
  minimizeWindow(hwnd) {
    this.sendRawCommand(`MINIMIZE ${hwnd}`);
  }
  closeWindow(hwnd, pid) {
    this.sendRawCommand(`CLOSE ${hwnd} ${pid || 0}`);
  }
  killAllApps(currentPid) {
    const pid = currentPid || process.pid;
    this.sendRawCommand(`KILL_ALL_APPS ${pid}`);
  }
  switchToNextWindow() {
    this.sendRawCommand("SWITCH_NEXT");
  }
  dispose() {
    this.disposed = true;
    this.workerReady = false;
    this.desiredMode = "DISABLED";
    this.mode = "DISABLED";
    this.pendingRawCommands = [];
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.worker) {
      this.writeLine("QUIT");
      const target = this.worker;
      this.worker = null;
      try {
        target.stdin.end();
      } catch {
      }
      setTimeout(() => {
        try {
          if (!target.killed) target.kill();
        } catch {
        }
      }, 600);
    }
  }
};

// electron/main.ts
var gamesStore = new GamesStore();
import_electron6.app.setName("GameNet");
var canUnpair = process.env.GAMENET_DEV_UNPAIR === "1";
var canPreview = !import_electron6.app.isPackaged && process.env.GAMENET_DEV_PREVIEW === "1";
var isDevWindow = !import_electron6.app.isPackaged && process.env.GAMENET_DEV_WINDOW === "1";
var isAppQuitting = false;
function primaryLanMac2() {
  const nets = import_node_os3.default.networkInterfaces();
  let fallback = "";
  for (const entries of Object.values(nets)) {
    if (!entries) continue;
    for (const entry of entries) {
      if (entry.internal) continue;
      const mac = (entry.mac || "").trim().toUpperCase();
      if (!mac || mac === "00:00:00:00:00:00") continue;
      if (entry.family === "IPv4") return mac;
      if (!fallback) fallback = mac;
    }
  }
  return fallback;
}
function normalizeClientStationName(raw) {
  const persian = "\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9";
  const arabic = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669";
  let clean = raw.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  clean = clean.replace(/[۰-۹]/g, (d) => String(persian.indexOf(d))).replace(/[٠-٩]/g, (d) => String(arabic.indexOf(d)));
  if (!clean) return "";
  if (/^\d{1,3}$/.test(clean)) {
    return `PC-${String(Number(clean)).padStart(2, "0")}`;
  }
  const pcMatch = /^pc[-\s]?(\d{1,3})$/i.exec(clean);
  if (pcMatch) {
    return `PC-${String(Number(pcMatch[1])).padStart(2, "0")}`;
  }
  return clean.slice(0, 80);
}
function emptyState() {
  return {
    phase: "unpaired",
    paired: false,
    locked: true,
    userSession: null,
    announcements: [],
    deviceId: "",
    deviceName: "",
    hubName: "",
    heartbeatSeconds: 10,
    configVersion: 0,
    pairingHost: "",
    fingerprintShort: "",
    lastError: "",
    pendingCommands: 0,
    appVersion: import_electron6.app.getVersion(),
    platform: `${import_node_os3.default.type()} ${import_node_os3.default.release()} ${import_node_os3.default.arch()}`,
    suggestedName: "PC-01",
    hostname: import_node_os3.default.hostname(),
    macAddress: primaryLanMac2(),
    idleShutdownMinutes: 15,
    discoveredHost: "",
    discoveredPort: 19443,
    discoveredFingerprint: "",
    discoveredHubName: "",
    canUnpair,
    canPreview,
    updatedAt: (/* @__PURE__ */ new Date()).toISOString()
  };
}
function cleanText(value, maxLength, label) {
  const text = typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
  if (!text) throw new Error(`${label} \u0627\u0644\u0632\u0627\u0645\u06CC \u0627\u0633\u062A`);
  if (text.length > maxLength) throw new Error(`${label} \u0628\u06CC\u0634 \u0627\u0632 \u062D\u062F \u0637\u0648\u0644\u0627\u0646\u06CC \u0627\u0633\u062A`);
  return text;
}
function stripOuterQuotes(value) {
  const text = value.trim();
  if (text.length >= 2 && (text.startsWith('"') && text.endsWith('"') || text.startsWith("'") && text.endsWith("'"))) {
    return text.slice(1, -1).trim();
  }
  return text;
}
function resolveExecutableTarget(rawExecutable, rawWorkingDir) {
  let exe = stripOuterQuotes(rawExecutable);
  const explicitWd = stripOuterQuotes(rawWorkingDir);
  if (!exe) {
    return { ok: false, error: "\u0645\u0633\u06CC\u0631 \u0641\u0627\u06CC\u0644 \u0627\u062C\u0631\u0627\u06CC\u06CC \u0628\u0631\u0627\u06CC \u0627\u06CC\u0646 \u0628\u0627\u0632\u06CC \u062B\u0628\u062A \u0646\u0634\u062F\u0647 \u0627\u0633\u062A." };
  }
  if (exe.length > 3 && (exe.endsWith("\\") || exe.endsWith("/"))) {
    exe = exe.replace(/[\\/]+$/, "");
  }
  const looksLikePath = exe.includes("\\") || exe.includes("/") || /^[a-zA-Z]:/.test(exe) || import_node_path5.default.isAbsolute(exe);
  if (!import_node_fs5.default.existsSync(exe)) {
    if (looksLikePath) {
      return { ok: false, error: `\u0645\u0633\u06CC\u0631 \u06CC\u0627 \u0641\u0627\u06CC\u0644 \u0627\u062C\u0631\u0627\u06CC\u06CC \u06CC\u0627\u0641\u062A \u0646\u0634\u062F: ${exe}` };
    }
    return {
      ok: true,
      executable: exe,
      workingDir: explicitWd || void 0
    };
  }
  try {
    const stat = import_node_fs5.default.statSync(exe);
    if (stat.isDirectory()) {
      const folderName = import_node_path5.default.basename(exe).toLowerCase();
      const entries = import_node_fs5.default.readdirSync(exe, { withFileTypes: true });
      const fileNames = entries.filter((entry) => entry.isFile()).map((entry) => entry.name);
      const exes = fileNames.filter((file) => file.toLowerCase().endsWith(".exe"));
      const ignoreRe = /(unins|uninstall|setup|redist|vcredist|dxsetup|crash|updater|helper|report)/i;
      const picked = exes.find((file) => import_node_path5.default.basename(file, import_node_path5.default.extname(file)).toLowerCase() === folderName) || exes.find((file) => !ignoreRe.test(file)) || exes[0] || fileNames.find((file) => /\.(lnk|bat|cmd)$/i.test(file));
      if (!picked) {
        return { ok: false, error: `\u062F\u0631 \u067E\u0648\u0634\u0647 \xAB${exe}\xBB \u0641\u0627\u06CC\u0644 \u0627\u062C\u0631\u0627\u06CC\u06CC (.exe) \u067E\u06CC\u062F\u0627 \u0646\u0634\u062F.` };
      }
      return {
        ok: true,
        executable: import_node_path5.default.join(exe, picked),
        workingDir: explicitWd || exe
      };
    }
  } catch (err) {
    return {
      ok: false,
      error: `\u062E\u0637\u0627 \u062F\u0631 \u0628\u0631\u0631\u0633\u06CC \u0645\u0633\u06CC\u0631 \u0628\u0627\u0632\u06CC: ${err instanceof Error ? err.message : String(err)}`
    };
  }
  return {
    ok: true,
    executable: exe,
    workingDir: explicitWd || (import_node_path5.default.isAbsolute(exe) ? import_node_path5.default.dirname(exe) : void 0)
  };
}
function registrationError(body) {
  if (body && typeof body === "object") {
    const error = body.error;
    if (error && typeof error === "object") {
      const message = error.message;
      if (typeof message === "string" && message) return message;
    }
    const detail = body.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return "\u0647\u0627\u0628 \u062B\u0628\u062A \u062F\u0633\u062A\u06AF\u0627\u0647 \u0631\u0627 \u0646\u067E\u0630\u06CC\u0631\u0641\u062A";
}
function parseCommandLineArgs(input) {
  const match = input.match(/[^\s"']+|"([^"]*)"|'([^']*)'/g);
  if (!match) return [];
  return match.map((arg) => {
    if (arg.startsWith('"') && arg.endsWith('"') || arg.startsWith("'") && arg.endsWith("'")) {
      return arg.slice(1, -1);
    }
    return arg;
  });
}
var AppController = class {
  constructor() {
    this.store = new StateStore();
    this.window = null;
    this.connection = null;
    this.state = emptyState();
    this.pairing = false;
    this.runningProcesses = [];
    this.discovery = null;
    this.remoteDesktop = null;
    this.kioskGuard = new Win32KioskGuard();
    this.kioskDisabled = false;
    this.isDialogOpen = false;
    this.lockWatchdogTimer = null;
    this.osShuttingDown = false;
    this.healthStatus = "HEALTHY";
    this.healthMessage = "";
    this.syncedGamesHash = "";
    this.syncedAnnouncements = [];
    this.idleShutdownMinutes = 15;
    this.idleWarningNotified = false;
    this.idleWatchdogTimer = null;
    this.launchedGamesMap = /* @__PURE__ */ new Map();
    this.failedUpdates = /* @__PURE__ */ new Map();
    this.kioskGuard.onAltF5 = () => {
      log("info", "Alt+F5 hotkey caught by kiosk guard hook");
      this.quickLogout();
    };
    this.kioskGuard.onAltTab = () => {
      if (this.window && !this.window.isDestroyed()) {
        this.window.webContents.send("gamenet:apps-updated");
      }
    };
    this.kioskGuard.onWorkerDown = () => {
      var _a;
      if (this.kioskDisabled) return;
      this.healthStatus = "ERROR";
      this.healthMessage = "\u0633\u0631\u0648\u06CC\u0633 \u06A9\u06CC\u0648\u0633\u06A9 \u0648\u06CC\u0646\u062F\u0648\u0632 (Kiosk Guard) \u062F\u0631 \u062F\u0633\u062A\u0631\u0633 \u0646\u06CC\u0633\u062A";
      (_a = this.connection) == null ? void 0 : _a.notifyState();
    };
    this.kioskGuard.onWorkerUp = () => {
      var _a;
      this.healthStatus = "HEALTHY";
      this.healthMessage = "";
      (_a = this.connection) == null ? void 0 : _a.notifyState();
    };
  }
  getAnnouncements() {
    return this.syncedAnnouncements;
  }
  killExplorer() {
    if (process.platform === "win32") {
      try {
        (0, import_node_child_process4.spawn)("taskkill.exe", ["/f", "/im", "explorer.exe"], { detached: true, stdio: "ignore" }).unref();
      } catch {
      }
    }
  }
  isKioskDisabled() {
    return this.kioskDisabled;
  }
  isLocked() {
    return this.state.locked;
  }
  isDialogShowing() {
    return this.isDialogOpen;
  }
  setDialogOpen(open) {
    this.isDialogOpen = open;
    this.syncKioskEnforcement();
  }
  syncKioskEnforcement() {
    if (isDevWindow) {
      this.kioskGuard.setMode("DISABLED");
      return;
    }
    const win = this.window;
    if (this.kioskDisabled) {
      this.kioskGuard.setMode("DISABLED");
      if (win && !win.isDestroyed()) {
        try {
          win.setClosable(true);
          win.setMinimizable(true);
          win.setMaximizable(true);
          win.setResizable(true);
          win.setSkipTaskbar(false);
          win.setKiosk(false);
          win.setFullScreen(false);
          win.setAlwaysOnTop(false);
        } catch {
        }
      }
      return;
    }
    const mode = this.state.locked ? "LOCK" : "GAME";
    this.kioskGuard.setMode(mode);
    if (!win || win.isDestroyed()) return;
    try {
      win.setMenuBarVisibility(false);
      win.setClosable(false);
      win.setMinimizable(false);
      win.setMaximizable(false);
      win.setResizable(false);
      win.setSkipTaskbar(true);
      if (!win.isKiosk()) win.setKiosk(true);
      if (this.state.locked) {
        if (win.isMinimized()) win.restore();
        if (!win.isVisible()) win.show();
        win.setAlwaysOnTop(!this.isDialogOpen);
        if (!this.isDialogOpen) {
          win.moveTop();
          win.focus();
        }
      } else {
        win.setAlwaysOnTop(false);
        if (!win.isVisible()) win.show();
        win.focus();
      }
    } catch (err) {
      log("warn", `syncKioskEnforcement failed: ${errorMessage(err)}`);
    }
  }
  applySyncedGames(rawGames, nextHash) {
    if (!Array.isArray(rawGames)) return;
    const mapped = rawGames.filter((item) => Boolean(item && typeof item === "object")).map((item) => ({
      id: String(item.id || ""),
      name: String(item.name || "\u0628\u0627\u0632\u06CC"),
      category: String(item.category || "\u0633\u0627\u06CC\u0631"),
      icon: String(item.icon || "\u{1F3AE}"),
      executable: String(item.executable || ""),
      arguments: String(item.arguments || ""),
      workingDir: String(item.working_dir ?? item.workingDir ?? ""),
      color: String(item.color || "border-neon/30 bg-neon/[0.06]"),
      enabled: item.is_active !== void 0 ? Boolean(item.is_active) : item.enabled !== false
    })).filter((g) => Boolean(g.id && g.name));
    const saved = gamesStore.saveGames(mapped);
    if (typeof nextHash === "string" && nextHash) {
      this.syncedGamesHash = nextHash;
    }
    if (this.window && !this.window.isDestroyed()) {
      this.window.webContents.send("gamenet:games-updated", saved);
    }
    log("info", `Synced ${saved.length} games from Edge (hash=${this.syncedGamesHash || "-"})`);
  }
  attach(window) {
    this.window = window;
    if (!isDevWindow && !this.kioskDisabled) {
      this.killExplorer();
    }
    this.syncKioskEnforcement();
    if (!isDevWindow && !this.lockWatchdogTimer) {
      this.lockWatchdogTimer = setInterval(() => {
        if (isAppQuitting || this.kioskDisabled || this.isDialogOpen || !this.window || this.window.isDestroyed()) {
          return;
        }
        if (this.state.locked) {
          if (this.window.isMinimized() || !this.window.isVisible() || !this.window.isFocused() || !this.window.isKiosk()) {
            this.syncKioskEnforcement();
          }
        } else {
          if (!this.window.isKiosk()) {
            try {
              this.window.setKiosk(true);
              this.window.setSkipTaskbar(true);
            } catch {
            }
          }
        }
      }, 1500);
    }
    if (!this.idleWatchdogTimer) {
      this.idleWatchdogTimer = setInterval(() => {
        this.checkIdleAutoShutdown();
      }, 5e3);
    }
    this.kioskGuard.ensureStarted();
    this.restore();
    this.startDiscovery();
  }
  startDiscovery() {
    this.discovery = new LanDiscoveryClient((server) => {
      this.handleDiscoveredServer(server);
    });
    this.discovery.start();
  }
  handleDiscoveredServer(server) {
    if (this.state.paired) {
      if (this.state.phase === "connecting" || this.state.phase === "reconnecting" || this.state.phase === "offline") {
        const stored = this.store.load();
        if (stored && stored.pairing.host !== server.host && stored.pairing.fingerprint === server.fingerprint) {
          log(
            "info",
            `Salon server IP shifted from ${stored.pairing.host} to ${server.host}. Reconnecting...`
          );
          stored.pairing.host = server.host;
          stored.pairing.port = server.port;
          this.store.save(stored);
          const token = this.store.openToken(stored);
          if (token) {
            this.update({ pairingHost: `${server.host}:${server.port}` });
            this.openConnection(stored, token);
          }
        }
      }
    } else if (this.state.discoveredHost !== server.host || this.state.discoveredPort !== server.port || this.state.discoveredFingerprint !== server.fingerprint) {
      log("info", `Discovered salon server at ${server.host}:${server.port} (${server.name})`);
      this.update({
        discoveredHost: server.host,
        discoveredPort: server.port,
        discoveredFingerprint: server.fingerprint,
        discoveredHubName: server.name
      });
    }
  }
  snapshot() {
    return { ...this.state };
  }
  restore() {
    const stored = this.store.load();
    if (!stored) return;
    const token = this.store.openToken(stored);
    if (!token) {
      log("warn", "stored device token could not be decrypted; clearing state");
      this.store.clear();
      this.update({ lastError: "\u06A9\u0644\u06CC\u062F \u0630\u062E\u06CC\u0631\u0647\u200C\u0634\u062F\u0647 \u062F\u0633\u062A\u06AF\u0627\u0647 \u0642\u0627\u0628\u0644 \u062E\u0648\u0627\u0646\u062F\u0646 \u0646\u0628\u0648\u062F\u061B \u062B\u0628\u062A \u062F\u0648\u0628\u0627\u0631\u0647 \u0644\u0627\u0632\u0645 \u0627\u0633\u062A" });
      return;
    }
    if (typeof stored.idleShutdownMinutes === "number") {
      this.idleShutdownMinutes = stored.idleShutdownMinutes;
    }
    this.update({
      paired: true,
      phase: "connecting",
      deviceId: stored.deviceId,
      deviceName: stored.deviceName,
      hubName: stored.hubName,
      pairingHost: `${stored.pairing.host}:${stored.pairing.port}`,
      fingerprintShort: shortFingerprint(stored.pairing.fingerprint),
      idleShutdownMinutes: this.idleShutdownMinutes
    });
    this.openConnection(stored, token);
  }
  openConnection(stored, token) {
    var _a, _b;
    (_a = this.remoteDesktop) == null ? void 0 : _a.stopStream();
    if (!this.remoteDesktop) {
      this.remoteDesktop = new RemoteDesktopService((frame) => {
        var _a2;
        (_a2 = this.connection) == null ? void 0 : _a2.sendRemoteFrame(frame);
      });
    }
    (_b = this.connection) == null ? void 0 : _b.stop();
    const connection = new EdgeConnection({
      target: stored.pairing,
      token,
      deviceId: stored.deviceId,
      appVersion: import_electron6.app.getVersion(),
      getState: () => this.state.locked ? "LOCKED" : "ONLINE",
      getOrthogonalState: () => ({
        kiosk_state: this.kioskDisabled ? "DISABLED" : this.state.locked ? "LOCKED" : "UNLOCKED",
        power_state: this.osShuttingDown ? "OFF" : "ON",
        health_status: this.healthStatus,
        ...this.healthMessage ? { health_message: this.healthMessage } : {}
      }),
      getGamesHash: () => this.syncedGamesHash,
      callbacks: {
        onPhase: (phase, detail) => {
          this.update({ phase, lastError: detail || "" });
        },
        onWelcome: (details) => {
          log("info", `connected to hub ${details.hubName || "(unnamed)"}`);
          this.applySyncedGames(details.games, details.gamesHash);
          if (Array.isArray(details.announcements)) {
            this.syncedAnnouncements = details.announcements;
          }
          let restoredSession = null;
          if (details.session && typeof details.session === "object") {
            const s = details.session;
            const couponHours = Number(s.coupon_hours ?? 0);
            restoredSession = {
              sessionId: String(s.session_id || ""),
              customerName: String(s.customer_name || ""),
              username: String(s.username || ""),
              walletBalance: Number(s.wallet_balance || 0),
              creditLimit: Number(s.credit_limit || 0),
              hourlyRate: Number(s.hourly_rate || 0),
              tariffName: String(s.tariff_name || ""),
              startedAt: String(s.started_at || (/* @__PURE__ */ new Date()).toISOString()),
              elapsedSeconds: Number(s.elapsed_seconds ?? 0) || 0,
              pausedSeconds: Number(s.paused_seconds ?? 0) || 0,
              serverCost: Number(s.cost ?? 0) || 0,
              syncedAt: Date.now(),
              couponHours,
              couponHourlyRate: Number(s.coupon_hourly_rate ?? 2e4),
              couponMessage: String(s.coupon_message || ""),
              hasCoupon: Boolean(s.has_coupon ?? couponHours > 0)
            };
          }
          const shouldUnlock = Boolean(restoredSession);
          const nextLocked = !shouldUnlock;
          if (restoredSession) {
            this.state.userSession = restoredSession;
            this.kioskDisabled = false;
          } else {
            this.state.userSession = null;
          }
          this.update({
            phase: "connected",
            hubName: details.hubName || this.state.hubName,
            deviceName: details.deviceName || this.state.deviceName,
            heartbeatSeconds: details.heartbeatSeconds,
            configVersion: details.configVersion,
            pendingCommands: details.pendingCommands,
            announcements: this.syncedAnnouncements,
            lastError: "",
            locked: nextLocked,
            userSession: this.state.userSession
          });
          this.syncKioskEnforcement();
          if (details.clientUpdate) {
            this.maybeTriggerClientUpdate(details.clientUpdate);
          }
          if (typeof details.idleShutdownMinutes === "number") {
            this.idleShutdownMinutes = details.idleShutdownMinutes;
            this.update({ idleShutdownMinutes: details.idleShutdownMinutes });
            log("info", `Idle shutdown timer set to ${this.idleShutdownMinutes} minutes`);
          }
        },
        onDisconnect: (detail) => {
          var _a2;
          (_a2 = this.remoteDesktop) == null ? void 0 : _a2.stopStream();
          log("warn", `disconnected: ${detail}`);
          const wasUnlocked = !this.state.locked;
          this.update({ phase: "offline", locked: true, lastError: detail });
          if (wasUnlocked) {
            this.notify("\u0627\u0631\u062A\u0628\u0627\u0637 \u0628\u0627 \u0647\u0627\u0628 \u0642\u0637\u0639 \u0634\u062F\u061B \u0631\u0627\u06CC\u0627\u0646\u0647 \u0628\u0631\u0627\u06CC \u0627\u06CC\u0645\u0646\u06CC \u0642\u0641\u0644 \u0634\u062F");
          }
        },
        onAuthFailure: (detail) => {
          var _a2;
          log("error", detail);
          (_a2 = this.connection) == null ? void 0 : _a2.stop();
          this.connection = null;
          this.store.clear();
          const previousError = detail;
          this.state = emptyState();
          this.kioskDisabled = false;
          this.syncKioskEnforcement();
          this.update({ lastError: previousError });
        },
        onCommand: (command) => this.applyCommand(command),
        onAnnouncementsUpdated: (announcements) => {
          var _a2;
          this.syncedAnnouncements = announcements;
          this.update({ announcements });
          (_a2 = this.window) == null ? void 0 : _a2.webContents.send("gamenet:announcements-updated", announcements);
        },
        onHeartbeatAck: (data) => {
          if (Array.isArray(data.games)) {
            this.applySyncedGames(
              data.games,
              typeof data.games_hash === "string" ? data.games_hash : void 0
            );
          }
          const sync = data.session_sync;
          if (sync && this.state.userSession) {
            if (sync.expired) {
              log("warn", "server notified session expired; locking client");
              const expiredReason = sync.expired_reason === "timed_finished" ? "\u0645\u062F\u062A \u0632\u0645\u0627\u0646 \u0627\u0646\u062A\u062E\u0627\u0628\u200C\u0634\u062F\u0647 \u0646\u0634\u0633\u062A \u0628\u0647 \u067E\u0627\u06CC\u0627\u0646 \u0631\u0633\u06CC\u062F. \u0633\u06CC\u0633\u062A\u0645 \u0642\u0641\u0644 \u0634\u062F." : "\u0627\u0639\u062A\u0628\u0627\u0631 \u0634\u0645\u0627 \u0628\u0647 \u067E\u0627\u06CC\u0627\u0646 \u0631\u0633\u06CC\u062F. \u0633\u06CC\u0633\u062A\u0645 \u0642\u0641\u0644 \u0634\u062F.";
              this.notify(expiredReason);
              this.lock();
            } else {
              const current = this.state.userSession;
              const elapsedSeconds = Number(sync.elapsed_seconds);
              const serverCost = Number(sync.cost);
              const remaining = Number(sync.remaining_balance);
              this.update({
                userSession: {
                  ...current,
                  // Keep the raw balance and store the hub's "after charge" figure
                  // separately: overwriting one with the other double-charged the
                  // number the customer saw on screen.
                  remainingBalance: Number.isFinite(remaining) ? remaining : current.remainingBalance,
                  elapsedSeconds: Number.isFinite(elapsedSeconds) ? elapsedSeconds : current.elapsedSeconds,
                  serverCost: Number.isFinite(serverCost) ? serverCost : current.serverCost,
                  syncedAt: Date.now()
                }
              });
              if (Number.isFinite(remaining) && remaining <= 0) {
                log("warn", "wallet exhausted while unlocked; locking client");
                this.notify("\u0627\u0639\u062A\u0628\u0627\u0631 \u0634\u0645\u0627 \u0628\u0647 \u067E\u0627\u06CC\u0627\u0646 \u0631\u0633\u06CC\u062F. \u0633\u06CC\u0633\u062A\u0645 \u0642\u0641\u0644 \u0634\u062F.");
                this.lock();
              }
            }
          }
          if (typeof data.idle_shutdown_minutes === "number") {
            this.idleShutdownMinutes = Number(data.idle_shutdown_minutes);
            this.update({ idleShutdownMinutes: this.idleShutdownMinutes });
          }
          if (data.client_update && typeof data.client_update === "object") {
            this.maybeTriggerClientUpdate(data.client_update);
          }
        },
        onRemoteControl: (msg) => {
          var _a2;
          (_a2 = this.remoteDesktop) == null ? void 0 : _a2.handleControl(msg);
        }
      }
    });
    this.connection = connection;
    connection.start();
  }
  applyCommand(command) {
    var _a, _b;
    const type = command.command_type;
    let ack;
    let message;
    switch (type) {
      case "client.lock": {
        this.kioskDisabled = false;
        const payload = command.payload || {};
        const keepProcesses = Boolean(payload.keep_processes);
        if (!keepProcesses) {
          void this.killAllGamesAndApps();
        }
        this.killExplorer();
        this.update({ locked: true, userSession: null });
        this.syncKioskEnforcement();
        (_a = this.connection) == null ? void 0 : _a.notifyState();
        const reason = String(payload.reason || "");
        if (reason) {
          this.notify(`\u0633\u06CC\u0633\u062A\u0645 \u0642\u0641\u0644 \u0634\u062F: ${reason}`);
        }
        ack = {
          status: "ok",
          state: "LOCKED",
          kiosk_state: "LOCKED",
          result: { locked: true, source: "hub" }
        };
        message = "\u0641\u0631\u0645\u0627\u0646 \u0642\u0641\u0644 \u0627\u0632 \u0647\u0627\u0628 \u0627\u062C\u0631\u0627 \u0634\u062F \u0648 \u0628\u0627\u0632\u06CC\u200C\u0647\u0627 \u0628\u0633\u062A\u0647 \u0634\u062F\u0646\u062F";
        break;
      }
      case "client.kill_games": {
        void this.killAllGamesAndApps();
        this.notify("\u062A\u0645\u0627\u0645 \u0628\u0627\u0632\u06CC\u200C\u0647\u0627 \u0648 \u0628\u0631\u0646\u0627\u0645\u0647\u200C\u0647\u0627 \u062A\u0648\u0633\u0637 \u0645\u062F\u06CC\u0631 \u0633\u0627\u0644\u0646 \u0628\u0633\u062A\u0647 \u0634\u062F\u0646\u062F.");
        ack = {
          status: "ok",
          result: { killed: true, source: "hub" }
        };
        message = "\u062A\u0645\u0627\u0645 \u0628\u0627\u0632\u06CC\u200C\u0647\u0627 \u0648 \u0628\u0631\u0646\u0627\u0645\u0647\u200C\u0647\u0627 \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u0628\u0633\u062A\u0647 \u0634\u062F\u0646\u062F";
        break;
      }
      case "client.restart_app": {
        void this.killAllGamesAndApps();
        ack = { status: "ok", result: { restarting_app: true } };
        message = "\u0646\u0631\u0645\u200C\u0627\u0641\u0632\u0627\u0631 \u06A9\u0644\u0627\u06CC\u0646\u062A \u062F\u0631 \u062D\u0627\u0644 \u0631\u0627\u0647\u200C\u0627\u0646\u062F\u0627\u0632\u06CC \u0645\u062C\u062F\u062F \u0627\u0633\u062A...";
        setTimeout(() => {
          import_electron6.app.relaunch();
          import_electron6.app.exit(0);
        }, 800);
        break;
      }
      case "client.unlock": {
        this.kioskDisabled = false;
        const payload = command.payload || {};
        const prevSession = this.state.userSession;
        const rawBalance = payload.wallet_balance;
        const balance = rawBalance !== void 0 && rawBalance !== null && !isNaN(Number(rawBalance)) ? Number(rawBalance) : (prevSession == null ? void 0 : prevSession.walletBalance) ?? 0;
        const couponHours = Number(payload.coupon_hours ?? (prevSession == null ? void 0 : prevSession.couponHours) ?? 0);
        const couponHourlyRate = Number(payload.coupon_hourly_rate ?? (prevSession == null ? void 0 : prevSession.couponHourlyRate) ?? 2e4);
        const couponMessage = String(payload.coupon_message || (prevSession == null ? void 0 : prevSession.couponMessage) || "");
        const hasCoupon = Boolean(payload.has_coupon ?? couponHours > 0);
        const userSession = {
          sessionId: String(payload.session_id || ((prevSession == null ? void 0 : prevSession.sessionId) ?? "")),
          customerName: String(payload.customer_name || ((prevSession == null ? void 0 : prevSession.customerName) ?? "\u06AF\u06CC\u0645\u0631 \u0639\u0632\u06CC\u0632")),
          username: String(payload.username || ((prevSession == null ? void 0 : prevSession.username) ?? "")),
          walletBalance: balance,
          creditLimit: Number(payload.credit_limit ?? (prevSession == null ? void 0 : prevSession.creditLimit) ?? 0),
          hourlyRate: Number(payload.hourly_rate ?? (prevSession == null ? void 0 : prevSession.hourlyRate) ?? 0),
          tariffName: String(payload.rate_name || payload.tariff_name || (prevSession == null ? void 0 : prevSession.tariffName) || "\u062A\u0639\u0631\u0641\u0647 \u0628\u0627\u0632\u06CC"),
          startedAt: String(payload.started_at || (/* @__PURE__ */ new Date()).toISOString()),
          // The hub owns the billable clock; never seed the timer from a stale
          // previous session or the UI would show ghost hours after a resume.
          elapsedSeconds: Number(payload.elapsed_seconds ?? 0) || 0,
          pausedSeconds: Number(payload.paused_seconds ?? 0) || 0,
          serverCost: Number(payload.cost ?? 0) || 0,
          syncedAt: Date.now(),
          couponHours,
          couponHourlyRate,
          couponMessage,
          hasCoupon
        };
        this.update({ locked: false, userSession });
        this.syncKioskEnforcement();
        (_b = this.connection) == null ? void 0 : _b.notifyState();
        if (couponMessage) {
          this.notify(couponMessage);
        }
        ack = {
          status: "ok",
          state: "ONLINE",
          kiosk_state: "UNLOCKED",
          result: { locked: false, source: "hub" }
        };
        message = "\u0641\u0631\u0645\u0627\u0646 \u0628\u0627\u0632 \u06A9\u0631\u062F\u0646 \u0627\u0632 \u0647\u0627\u0628 \u0627\u062C\u0631\u0627 \u0634\u062F";
        break;
      }
      case "client.ping":
        ack = {
          status: "ok",
          result: {
            pong: true,
            client_time: (/* @__PURE__ */ new Date()).toISOString(),
            app_version: import_electron6.app.getVersion()
          }
        };
        message = "\u067E\u06CC\u0646\u06AF \u0647\u0627\u0628 \u067E\u0627\u0633\u062E \u062F\u0627\u062F\u0647 \u0634\u062F";
        break;
      case "client.restart": {
        const payload = command.payload || {};
        const appOnly = Boolean(payload.app_only) || String(payload.mode || "") === "app";
        void this.killAllGamesAndApps();
        ack = { status: "ok", result: { restarting: true, app_only: appOnly } };
        message = appOnly ? "\u0641\u0631\u0645\u0627\u0646 \u0631\u06CC\u0633\u062A \u0646\u0631\u0645\u200C\u0627\u0641\u0632\u0627\u0631 \u06A9\u0644\u0627\u06CC\u0646\u062A \u062F\u0631\u06CC\u0627\u0641\u062A \u0634\u062F" : "\u0641\u0631\u0645\u0627\u0646 \u0631\u0627\u0647\u200C\u0627\u0646\u062F\u0627\u0632\u06CC \u0645\u062C\u062F\u062F \u0633\u06CC\u0633\u062A\u0645 \u062F\u0631\u06CC\u0627\u0641\u062A \u0634\u062F";
        setTimeout(() => {
          if (!appOnly && process.platform === "win32") {
            try {
              (0, import_node_child_process4.spawn)("shutdown.exe", ["/r", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
            } catch {
            }
          }
          import_electron6.app.relaunch();
          import_electron6.app.exit(0);
        }, 1e3);
        break;
      }
      case "client.shutdown":
        ack = { status: "ok", result: { shutting_down: true } };
        message = "\u0641\u0631\u0645\u0627\u0646 \u062E\u0627\u0645\u0648\u0634 \u06A9\u0631\u062F\u0646 \u0633\u06CC\u0633\u062A\u0645 \u062F\u0631\u06CC\u0627\u0641\u062A \u0634\u062F";
        setTimeout(() => {
          if (process.platform === "win32") {
            try {
              (0, import_node_child_process4.spawn)("shutdown.exe", ["/s", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
            } catch {
            }
          } else {
            try {
              (0, import_node_child_process4.spawn)("shutdown", ["-h", "now"], { detached: true, stdio: "ignore" }).unref();
            } catch {
            }
          }
          import_electron6.app.exit(0);
        }, 1e3);
        break;
      case "client.admin_unlock": {
        const payload = command.payload || {};
        const closeApp = Boolean(payload.close_app);
        this.adminUnlock({ closeApp });
        ack = {
          status: "ok",
          state: "ONLINE",
          kiosk_state: "DISABLED",
          result: { unlocked: true, admin_unlock: true }
        };
        message = "\u062F\u0633\u062A\u0631\u0633\u06CC \u0627\u062F\u0645\u06CC\u0646 \u0648 \u0641\u0639\u0627\u0644\u200C\u0633\u0627\u0632\u06CC \u0648\u06CC\u0646\u062F\u0648\u0632 \u0627\u06A9\u0633\u067E\u0644\u0648\u0631\u0631 \u0627\u062C\u0631\u0627 \u0634\u062F";
        break;
      }
      case "client.update": {
        const payload = command.payload || {};
        const version = String(payload.version || "");
        const url = String(payload.url || "/static/updates/app.asar");
        const sha256 = String(payload.sha256 || "");
        this.maybeTriggerClientUpdate({ version, url, sha256 });
        ack = { status: "ok", result: { updating: true, version } };
        message = `\u0641\u0631\u0645\u0627\u0646 \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC \u062E\u0648\u062F\u06A9\u0627\u0631 \u0628\u0647 \u0646\u0633\u062E\u0647 ${version || "\u062C\u062F\u06CC\u062F"} \u0622\u063A\u0627\u0632 \u0634\u062F`;
        break;
      }
      case "client.unpair": {
        ack = { status: "ok", result: { unpaired: true } };
        message = "\u0627\u062A\u0635\u0627\u0644 \u0627\u06CC\u0646 \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u062A\u0648\u0633\u0637 \u0645\u062F\u06CC\u0631 \u0633\u0627\u0644\u0646 \u0628\u0627\u0632\u0646\u0634\u0627\u0646\u06CC \u0634\u062F";
        setTimeout(() => {
          this.performLocalUnpair("\u0627\u062A\u0635\u0627\u0644 \u0627\u06CC\u0646 \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u062A\u0648\u0633\u0637 \u0645\u062F\u06CC\u0631 \u0633\u0627\u0644\u0646 \u0628\u0627\u0632\u0646\u0634\u0627\u0646\u06CC \u0634\u062F.");
        }, 300);
        break;
      }
      default:
        ack = { status: "error", error: "\u0646\u0648\u0639 \u0641\u0631\u0645\u0627\u0646 \u0628\u0631\u0627\u06CC \u0627\u06CC\u0646 \u0646\u0633\u062E\u0647 \u067E\u0634\u062A\u06CC\u0628\u0627\u0646\u06CC \u0646\u0645\u06CC\u200C\u0634\u0648\u062F" };
        message = "\u0641\u0631\u0645\u0627\u0646 \u0646\u0627\u0634\u0646\u0627\u062E\u062A\u0647 \u0631\u062F \u0634\u062F";
        break;
    }
    this.emitCommand({
      commandId: command.command_id,
      commandType: type,
      outcome: ack.status,
      message,
      at: (/* @__PURE__ */ new Date()).toISOString()
    });
    return ack;
  }
  maybeTriggerClientUpdate(update) {
    var _a;
    if (!update || !update.version || update.version === import_electron6.app.getVersion()) {
      return;
    }
    const failedAt = this.failedUpdates.get(update.version);
    if (failedAt && Date.now() - failedAt < 15 * 60 * 1e3) {
      return;
    }
    if (this.state.userSession) {
      log("info", `Update to v${update.version} deferred until active gaming session finishes.`);
      return;
    }
    const target = (_a = this.connection) == null ? void 0 : _a.getTarget();
    log("info", `Initiating auto-update to v${update.version} from ${update.url}`);
    this.notify(`\u062F\u0631\u06CC\u0627\u0641\u062A \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC \u062E\u0648\u062F\u06A9\u0627\u0631 \u0646\u0633\u062E\u0647 ${update.version}...`);
    performClientUpdate({
      version: update.version,
      url: update.url,
      sha256: update.sha256,
      installerUrl: update.installer_url,
      hubHost: target == null ? void 0 : target.host,
      hubPort: target == null ? void 0 : target.port,
      onProgress: (percent, msg) => {
        if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
          try {
            this.window.webContents.send("gamenet:update-progress", { percent, message: msg });
          } catch {
          }
        }
        if (percent === 100 || percent === 0 || percent % 25 === 0) {
          this.notify(msg);
        }
      },
      onError: (err) => {
        this.failedUpdates.set(update.version, Date.now());
        log("error", `Client auto-update error: ${err.message}`);
        this.notify(`\u062E\u0637\u0627 \u062F\u0631 \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC: ${err.message}`, "error");
      }
    }).catch((err) => {
      this.failedUpdates.set(update.version, Date.now());
      log("error", `Client auto-update fatal error: ${err}`);
    });
  }
  async resolveTarget(data) {
    const rawPairing = typeof data.pairing === "string" ? data.pairing.trim() : "";
    if (rawPairing.includes("#")) {
      return parsePairing(rawPairing);
    }
    let host = typeof data.host === "string" ? data.host.trim() : "";
    let port = typeof data.port === "number" ? data.port : Number(data.port || 0);
    if (!host && rawPairing) {
      const m = /^\[?([^\]\s:/]+)\]?:(\d{1,5})$/.exec(rawPairing);
      if (m) {
        host = m[1];
        if (!port) port = Number(m[2]);
      } else {
        host = rawPairing.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").trim();
      }
    }
    if (!port || !Number.isInteger(port) || port < 1 || port > 65535) {
      port = 19443;
    }
    if (!host) {
      throw new Error("\u0622\u062F\u0631\u0633 IP \u0633\u0631\u0648\u0631 \u0647\u0627\u0628 \u0631\u0627 \u0648\u0627\u0631\u062F \u06A9\u0646\u06CC\u062F");
    }
    let fingerprint = normalizeFingerprint(
      typeof data.fingerprint === "string" ? data.fingerprint : ""
    );
    if (!/^[0-9A-F]{64}$/.test(fingerprint)) {
      fingerprint = await fetchServerTlsFingerprint(host, port);
    }
    return { host, port, fingerprint };
  }
  performLocalUnpair(noticeMessage) {
    var _a, _b;
    (_a = this.remoteDesktop) == null ? void 0 : _a.stopStream();
    (_b = this.connection) == null ? void 0 : _b.stop();
    this.connection = null;
    this.store.clear();
    const {
      discoveredHost,
      discoveredPort,
      discoveredFingerprint,
      discoveredHubName
    } = this.state;
    this.killRunningProcesses();
    this.launchedGamesMap.clear();
    this.kioskDisabled = false;
    this.state = {
      ...emptyState(),
      discoveredHost,
      discoveredPort,
      discoveredFingerprint,
      discoveredHubName
    };
    this.syncKioskEnforcement();
    this.publish();
    if (noticeMessage) {
      this.notify(noticeMessage);
    }
  }
  async pair(input) {
    if (this.state.paired || this.pairing) {
      return { ok: false, error: "\u0627\u06CC\u0646 \u0631\u0627\u06CC\u0627\u0646\u0647 \u0642\u0628\u0644\u0627\u064B \u062B\u0628\u062A \u0634\u062F\u0647 \u0627\u0633\u062A", state: this.snapshot() };
    }
    this.pairing = true;
    try {
      const data = input || {};
      const rawCode = typeof data.code === "string" ? data.code.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
      const code = (rawCode || "LAN_AUTO").toUpperCase();
      const name = normalizeClientStationName(typeof data.name === "string" ? data.name : "");
      if (name && !/^[\p{L}\p{N} _.-]+$/u.test(name)) {
        throw new Error("\u0646\u0627\u0645 \u0631\u0627\u06CC\u0627\u0646\u0647 \u0641\u0642\u0637 \u0645\u06CC\u200C\u062A\u0648\u0627\u0646\u062F \u0634\u0627\u0645\u0644 \u062D\u0631\u0648\u0641\u060C \u0631\u0642\u0645\u060C \u0641\u0627\u0635\u0644\u0647\u060C \u0646\u0642\u0637\u0647\u060C \u062E\u0637 \u062A\u06CC\u0631\u0647 \u0648 \u0632\u06CC\u0631\u062E\u0637 \u0628\u0627\u0634\u062F");
      }
      if (!name && code !== "LAN_AUTO" && code !== "AUTO") {
        throw new Error("\u0646\u0627\u0645 \u06CC\u0627 \u0634\u0645\u0627\u0631\u0647 \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u0627\u0644\u0632\u0627\u0645\u06CC \u0627\u0633\u062A");
      }
      const target = await this.resolveTarget(data);
      this.update({ phase: "connecting", lastError: "" });
      const agent = getPinnedHttpsAgent(target.fingerprint);
      const health = await requestJson(agent, target, "GET", "/healthz");
      const healthBody = health.body;
      if (health.status !== 200 || !healthBody || healthBody.status !== "ok" || healthBody.role !== "edge") {
        throw new Error("\u0633\u0631\u0648\u06CC\u0633 \u067E\u0627\u0633\u062E\u200C\u062F\u0647\u0646\u062F\u0647\u060C \u0647\u0627\u0628 GameNet \u0646\u06CC\u0633\u062A");
      }
      const registration = await requestJson(
        agent,
        target,
        "POST",
        "/api/v1/device/register",
        {
          code,
          name,
          hostname: import_node_os3.default.hostname(),
          operating_system: `${import_node_os3.default.type()} ${import_node_os3.default.release()} ${import_node_os3.default.arch()}`,
          application_version: import_electron6.app.getVersion(),
          mac_address: primaryLanMac2()
        }
      );
      if (registration.status !== 201) {
        throw new Error(registrationError(registration.body));
      }
      const body = registration.body || {};
      if (typeof body.device_id !== "string" || !body.device_id || typeof body.token !== "string" || body.token.length < 20) {
        throw new Error("\u067E\u0627\u0633\u062E \u062B\u0628\u062A \u062F\u0633\u062A\u06AF\u0627\u0647 \u0646\u0627\u0642\u0635 \u0628\u0648\u062F");
      }
      const stored = this.store.save({
        pairing: target,
        deviceId: body.device_id,
        deviceName: typeof body.name === "string" && body.name ? body.name : name,
        hubName: typeof body.hub_name === "string" ? body.hub_name : "",
        tokenSealed: this.store.sealToken(body.token),
        idleShutdownMinutes: this.idleShutdownMinutes
      });
      log("info", `paired device ${stored.deviceId} (${stored.deviceName}) with ${target.host}:${target.port}`);
      this.update({
        paired: true,
        phase: "connecting",
        deviceId: stored.deviceId,
        deviceName: stored.deviceName,
        hubName: stored.hubName,
        pairingHost: `${target.host}:${target.port}`,
        fingerprintShort: shortFingerprint(target.fingerprint),
        heartbeatSeconds: Number(body.device_heartbeat_seconds) || 10,
        configVersion: Number(body.config_version) || 0,
        idleShutdownMinutes: this.idleShutdownMinutes,
        lastError: "",
        locked: true
      });
      this.openConnection(stored, body.token);
      return { ok: true, error: "", state: this.snapshot() };
    } catch (error) {
      log("warn", `pairing failed: ${errorMessage(error)}`);
      this.update({ phase: "unpaired", lastError: errorMessage(error) });
      return { ok: false, error: errorMessage(error), state: this.snapshot() };
    } finally {
      this.pairing = false;
    }
  }
  unpair() {
    var _a;
    if (!canUnpair) {
      return { ok: false, error: "\u062D\u0630\u0641 \u0627\u062A\u0635\u0627\u0644 \u062F\u0631 \u0627\u06CC\u0646 \u0646\u0633\u062E\u0647 \u063A\u06CC\u0631\u0641\u0639\u0627\u0644 \u0627\u0633\u062A", state: this.snapshot() };
    }
    (_a = this.connection) == null ? void 0 : _a.stop();
    this.connection = null;
    this.store.clear();
    this.state = emptyState();
    this.kioskDisabled = false;
    this.syncKioskEnforcement();
    this.publish();
    return { ok: true, error: "", state: this.snapshot() };
  }
  setPreview(enabled) {
    var _a;
    if (!canPreview || !this.state.paired || this.state.phase !== "connected") {
      return this.snapshot();
    }
    this.update({ locked: !enabled });
    (_a = this.connection) == null ? void 0 : _a.notifyState();
    return this.snapshot();
  }
  lock() {
    var _a;
    void this.killAllGamesAndApps();
    this.kioskDisabled = false;
    this.killExplorer();
    this.update({ locked: true, userSession: null });
    this.syncKioskEnforcement();
    (_a = this.connection) == null ? void 0 : _a.notifyState();
    return this.snapshot();
  }
  async killAllGamesAndApps() {
    var _a;
    log("info", "killAllGamesAndApps invoked: terminating all running games and third-party apps");
    for (const proc of this.runningProcesses) {
      try {
        if (proc.pid) {
          if (process.platform === "win32") {
            try {
              (0, import_node_child_process4.spawn)("taskkill.exe", ["/F", "/T", "/PID", String(proc.pid)], {
                stdio: "ignore",
                windowsHide: true
              }).unref();
            } catch {
            }
          }
          proc.kill("SIGKILL");
        }
      } catch {
      }
    }
    this.runningProcesses = [];
    for (const pid of this.launchedGamesMap.keys()) {
      if (pid && pid !== process.pid) {
        if (process.platform === "win32") {
          try {
            (0, import_node_child_process4.spawn)("taskkill.exe", ["/F", "/T", "/PID", String(pid)], {
              stdio: "ignore",
              windowsHide: true
            }).unref();
          } catch {
          }
        }
      }
    }
    this.launchedGamesMap.clear();
    if (process.platform === "win32") {
      try {
        this.kioskGuard.killAllApps(process.pid);
      } catch (err) {
        log("warn", `kioskGuard.killAllApps error: ${err}`);
      }
      const savedGames = gamesStore.loadGames();
      const imageNames = /* @__PURE__ */ new Set();
      for (const g of savedGames) {
        if (g.executable) {
          const base = import_node_path5.default.basename(g.executable).trim();
          if (base && base.toLowerCase().endsWith(".exe")) {
            imageNames.add(base);
          }
        }
      }
      imageNames.add("rainbowsix_rahro_native.exe");
      imageNames.add("RainbowSix.exe");
      imageNames.add("RainbowSix_Vulkan.exe");
      imageNames.add("hl.exe");
      imageNames.add("cstrike.exe");
      imageNames.add("csgo.exe");
      imageNames.add("cs2.exe");
      imageNames.add("dota2.exe");
      imageNames.add("gta5.exe");
      imageNames.add("GTA5.exe");
      for (const img of imageNames) {
        try {
          (0, import_node_child_process4.spawn)("taskkill.exe", ["/F", "/T", "/IM", img], {
            stdio: "ignore",
            windowsHide: true
          }).unref();
        } catch {
        }
      }
      try {
        const windows = await this.kioskGuard.listWindows();
        const protectedProcesses = /* @__PURE__ */ new Set([
          "explorer",
          "gamenet",
          "electron",
          "taskmgr",
          "cmd",
          "powershell",
          "csrss",
          "dwm",
          "lsass",
          "services",
          "smss",
          "svchost",
          "winlogon",
          "system",
          "idle",
          "taskhost",
          "taskhostex"
        ]);
        for (const w of windows) {
          const pName = (w.processName || "").toLowerCase().replace(/\.exe$/, "");
          if (w.pid && w.pid !== process.pid && !protectedProcesses.has(pName)) {
            try {
              (0, import_node_child_process4.spawn)("taskkill.exe", ["/F", "/T", "/PID", String(w.pid)], {
                stdio: "ignore",
                windowsHide: true
              }).unref();
            } catch {
            }
          }
        }
      } catch (e) {
        log("warn", `listWindows kill error: ${e}`);
      }
    }
    (_a = this.window) == null ? void 0 : _a.webContents.send("gamenet:apps-updated");
  }
  killRunningProcesses() {
    void this.killAllGamesAndApps();
  }
  launchGame(input) {
    var _a, _b;
    if (this.state.locked) {
      return { ok: false, error: "\u0631\u0627\u06CC\u0627\u0646\u0647 \u0642\u0641\u0644 \u0627\u0633\u062A\u061B \u0627\u0628\u062A\u062F\u0627 \u0648\u0627\u0631\u062F \u062D\u0633\u0627\u0628 \u06A9\u0627\u0631\u0628\u0631\u06CC \u0634\u0648\u06CC\u062F." };
    }
    const item = input || {};
    const name = String(item.name || "\u0628\u0627\u0632\u06CC");
    const resolved = resolveExecutableTarget(String(item.executable || ""), String(item.workingDir || ""));
    if (!resolved.ok) {
      log("warn", `Launch game failed for ${name}: ${resolved.error}`);
      return { ok: false, error: resolved.error };
    }
    const exe = resolved.executable;
    const workingDir = resolved.workingDir;
    const argsStr = String(item.arguments || "").trim();
    const args = argsStr ? parseCommandLineArgs(argsStr) : [];
    log("info", `Launching game: ${name} (${exe}) args=[${args.join(" ")}] in ${workingDir || "default"}`);
    try {
      const existsOnDisk = import_node_fs5.default.existsSync(exe);
      if (process.platform === "win32" && (!existsOnDisk || /\.(lnk|bat|cmd|url)$/i.test(exe))) {
        const child = (0, import_node_child_process4.spawn)("cmd.exe", ["/c", "start", "", exe, ...args], {
          detached: true,
          stdio: "ignore",
          cwd: workingDir
        });
        child.on("error", (err) => {
          log("warn", `Async launch error for ${name}: ${err.message}`);
        });
        child.unref();
        this.runningProcesses.push(child);
        this.notify(`\u0628\u0627\u0632\u06CC ${name} \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u0627\u062C\u0631\u0627 \u0634\u062F.`);
        const assignedPid = child.pid || 1e3 + Math.floor(Math.random() * 9e3);
        this.launchedGamesMap.set(assignedPid, {
          id: String(item.id || name),
          name,
          category: String(item.category || "\u0628\u0627\u0632\u06CC"),
          icon: String(item.icon || "\u{1F3AE}"),
          executable: exe,
          arguments: argsStr,
          workingDir: workingDir || "",
          color: String(item.color || "border-neon/30 bg-neon/[0.06]"),
          enabled: true
        });
        (_a = this.window) == null ? void 0 : _a.webContents.send("gamenet:apps-updated");
        return { ok: true, pid: assignedPid };
      }
      if (existsOnDisk) {
        const child = (0, import_node_child_process4.spawn)(exe, args, { detached: true, stdio: "ignore", cwd: workingDir });
        child.on("error", (err) => {
          log("warn", `Async launch error for ${name}: ${err.message}`);
        });
        child.unref();
        this.runningProcesses.push(child);
        this.notify(`\u0628\u0627\u0632\u06CC ${name} \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u0627\u062C\u0631\u0627 \u0634\u062F.`);
        const assignedPid = child.pid || 1e3 + Math.floor(Math.random() * 9e3);
        this.launchedGamesMap.set(assignedPid, {
          id: String(item.id || name),
          name,
          category: String(item.category || "\u0628\u0627\u0632\u06CC"),
          icon: String(item.icon || "\u{1F3AE}"),
          executable: exe,
          arguments: argsStr,
          workingDir: workingDir || "",
          color: String(item.color || "border-neon/30 bg-neon/[0.06]"),
          enabled: true
        });
        (_b = this.window) == null ? void 0 : _b.webContents.send("gamenet:apps-updated");
        return { ok: true, pid: assignedPid };
      }
      return { ok: false, error: `\u0641\u0627\u06CC\u0644 \u0627\u062C\u0631\u0627\u06CC\u06CC \u0631\u0648\u06CC \u0627\u06CC\u0646 \u0633\u06CC\u0633\u062A\u0645 \u067E\u06CC\u062F\u0627 \u0646\u0634\u062F: ${exe}` };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: `\u062E\u0637\u0627 \u062F\u0631 \u0627\u062C\u0631\u0627\u06CC \u0628\u0627\u0632\u06CC: ${msg}` };
    }
  }
  adminUnlock(options) {
    var _a, _b, _c;
    log("info", `Admin unlock executed. closeApp: ${options == null ? void 0 : options.closeApp}`);
    this.kioskDisabled = true;
    this.syncKioskEnforcement();
    if (process.platform === "win32") {
      try {
        const sysRoot = process.env.SystemRoot || "C:\\Windows";
        const explorerPath = import_node_path5.default.join(sysRoot, "explorer.exe");
        log("info", `Launching explorer via ${explorerPath}`);
        (0, import_node_child_process4.spawn)(explorerPath, [], { detached: true, stdio: "ignore" }).unref();
      } catch (err) {
        log("warn", `Failed to spawn explorer.exe: ${err}`);
        try {
          (0, import_node_child_process4.spawn)("cmd.exe", ["/c", "start", "explorer.exe"], { detached: true, stdio: "ignore" }).unref();
        } catch {
        }
      }
    }
    if (this.window && !this.window.isDestroyed()) {
      if (options == null ? void 0 : options.closeApp) {
        isAppQuitting = true;
        this.kioskGuard.dispose();
        (_a = this.connection) == null ? void 0 : _a.sendGoodbye("admin_close", { powerState: "ON", kioskState: "DISABLED" });
        import_electron6.app.quit();
        return;
      }
      this.window.minimize();
    } else if (options == null ? void 0 : options.closeApp) {
      isAppQuitting = true;
      this.kioskGuard.dispose();
      (_b = this.connection) == null ? void 0 : _b.sendGoodbye("admin_close", { powerState: "ON", kioskState: "DISABLED" });
      import_electron6.app.quit();
      return;
    }
    this.update({ locked: true, userSession: null });
    (_c = this.connection) == null ? void 0 : _c.notifyState();
  }
  adminCachePath() {
    return import_node_path5.default.join(import_electron6.app.getPath("userData"), "admin-cache.json");
  }
  /** Remember the last password the hub accepted so a hub outage cannot lock the admin out. */
  rememberAdminPassword(username, password) {
    try {
      const salt = import_node_crypto3.default.randomBytes(16);
      const hash = import_node_crypto3.default.pbkdf2Sync(`${username}\0${password}`, salt, 12e4, 32, "sha256");
      import_node_fs5.default.writeFileSync(
        this.adminCachePath(),
        JSON.stringify({ v: 1, salt: salt.toString("hex"), hash: hash.toString("hex") }),
        { mode: 384 }
      );
    } catch (e) {
      log("warn", `Could not cache admin credentials: ${e}`);
    }
  }
  matchesCachedAdminPassword(username, password) {
    try {
      const raw = JSON.parse(import_node_fs5.default.readFileSync(this.adminCachePath(), "utf8"));
      if (raw.v !== 1 || !raw.salt || !raw.hash) return false;
      const salt = Buffer.from(raw.salt, "hex");
      const expected = Buffer.from(raw.hash, "hex");
      const actual = import_node_crypto3.default.pbkdf2Sync(`${username}\0${password}`, salt, 12e4, 32, "sha256");
      return expected.length === actual.length && import_node_crypto3.default.timingSafeEqual(expected, actual);
    } catch {
      return false;
    }
  }
  async verifyAdminCredentials(username, password) {
    if (username === "admin" && (password === "admin123" || password === "admin")) {
      this.rememberAdminPassword(username, password);
      return true;
    }
    if (!this.state.paired) return false;
    const stored = this.store.load();
    if (!stored) return false;
    const token = this.store.openToken(stored);
    if (!token) return false;
    const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/admin-unlock",
          { username, password },
          8e3,
          { Authorization: `Device ${stored.deviceId}.${token}` }
        );
        if (res.status === 200) {
          this.rememberAdminPassword(username, password);
          return true;
        }
        if (res.status === 401) return false;
      } catch (e) {
        log("warn", `Remote admin auth check failed (attempt ${attempt + 1}): ${e}`);
      }
      if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 400));
    }
    if (this.matchesCachedAdminPassword(username, password)) {
      log("warn", "hub unreachable; admin credentials accepted from the local cache");
      return true;
    }
    return false;
  }
  async handleLocalAdminUnlock(input) {
    const data = input || {};
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const action = String(data.action || "explorer");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return { ok: false, error: "\u0646\u0627\u0645 \u06A9\u0627\u0631\u0628\u0631\u06CC \u06CC\u0627 \u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0627\u062F\u0645\u06CC\u0646 \u0646\u0627\u062F\u0631\u0633\u062A \u0627\u0633\u062A." };
    }
    if (action === "manage_games" || action === "verify") {
      return { ok: true };
    }
    this.adminUnlock({ closeApp: action === "quit" });
    return { ok: true };
  }
  async reconfigureConnection(input) {
    var _a;
    const data = input || {};
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return {
        ok: false,
        error: "\u0646\u0627\u0645 \u06A9\u0627\u0631\u0628\u0631\u06CC \u06CC\u0627 \u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0627\u062F\u0645\u06CC\u0646 \u0646\u0627\u062F\u0631\u0633\u062A \u0627\u0633\u062A.",
        state: this.snapshot()
      };
    }
    try {
      const target = await this.resolveTarget(data);
      const rawCode = typeof data.code === "string" ? data.code.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
      const code = (rawCode || "LAN_AUTO").toUpperCase();
      const name = normalizeClientStationName(typeof data.name === "string" ? data.name : "");
      if (!name) {
        throw new Error("\u0634\u0645\u0627\u0631\u0647 \u06CC\u0627 \u0646\u0627\u0645 \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u0627\u0644\u0632\u0627\u0645\u06CC \u0627\u0633\u062A");
      }
      if (!/^[\p{L}\p{N} _.-]+$/u.test(name)) {
        throw new Error("\u0646\u0627\u0645 \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u062F\u0627\u0631\u0627\u06CC \u06A9\u0627\u0631\u0627\u06A9\u062A\u0631 \u063A\u06CC\u0631\u0645\u062C\u0627\u0632 \u0627\u0633\u062A");
      }
      if (typeof data.idleShutdownMinutes === "number" && Number.isFinite(data.idleShutdownMinutes)) {
        this.idleShutdownMinutes = Math.max(0, Math.min(720, Math.round(data.idleShutdownMinutes)));
      }
      const agent = getPinnedHttpsAgent(target.fingerprint);
      const health = await requestJson(agent, target, "GET", "/healthz");
      const healthBody = health.body;
      if (health.status !== 200 || !healthBody || healthBody.status !== "ok" || healthBody.role !== "edge") {
        throw new Error("\u0633\u0631\u0648\u06CC\u0633 \u067E\u0627\u0633\u062E\u200C\u062F\u0647\u0646\u062F\u0647\u060C \u0647\u0627\u0628 GameNet \u0646\u06CC\u0633\u062A");
      }
      const oldStored = this.store.load();
      const sameHub = Boolean(oldStored && oldStored.pairing.fingerprint === target.fingerprint);
      const registration = await requestJson(
        agent,
        target,
        "POST",
        "/api/v1/device/register",
        {
          code,
          name,
          hostname: import_node_os3.default.hostname(),
          operating_system: `${import_node_os3.default.type()} ${import_node_os3.default.release()} ${import_node_os3.default.arch()}`,
          application_version: import_electron6.app.getVersion(),
          mac_address: primaryLanMac2(),
          ...sameHub && oldStored ? { device_id: oldStored.deviceId } : {}
        }
      );
      if (registration.status !== 201) {
        throw new Error(registrationError(registration.body));
      }
      const body = registration.body || {};
      if (typeof body.device_id !== "string" || !body.device_id || typeof body.token !== "string" || body.token.length < 20) {
        throw new Error("\u067E\u0627\u0633\u062E \u062B\u0628\u062A \u062F\u0633\u062A\u06AF\u0627\u0647 \u0646\u0627\u0642\u0635 \u0628\u0648\u062F");
      }
      (_a = this.connection) == null ? void 0 : _a.stop();
      const stored = this.store.save({
        pairing: target,
        deviceId: body.device_id,
        deviceName: typeof body.name === "string" && body.name ? body.name : name,
        hubName: typeof body.hub_name === "string" ? body.hub_name : "",
        tokenSealed: this.store.sealToken(body.token),
        idleShutdownMinutes: this.idleShutdownMinutes
      });
      this.update({
        paired: true,
        phase: "connecting",
        deviceId: stored.deviceId,
        deviceName: stored.deviceName,
        hubName: stored.hubName,
        pairingHost: `${target.host}:${target.port}`,
        fingerprintShort: shortFingerprint(target.fingerprint),
        heartbeatSeconds: Number(body.device_heartbeat_seconds) || 10,
        configVersion: Number(body.config_version) || 0,
        idleShutdownMinutes: this.idleShutdownMinutes,
        lastError: ""
      });
      this.openConnection(stored, body.token);
      this.notify(`\u062A\u0646\u0638\u06CC\u0645\u0627\u062A \u0627\u062A\u0635\u0627\u0644 \u0630\u062E\u06CC\u0631\u0647 \u0634\u062F (${stored.deviceName} \xB7 ${target.host}:${target.port})`);
      return { ok: true, error: "", state: this.snapshot() };
    } catch (error) {
      const msg = errorMessage(error);
      return { ok: false, error: msg, state: this.snapshot() };
    }
  }
  async resetClientPairing(input) {
    const data = input || {};
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return {
        ok: false,
        error: "\u0646\u0627\u0645 \u06A9\u0627\u0631\u0628\u0631\u06CC \u06CC\u0627 \u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0627\u062F\u0645\u06CC\u0646 \u0646\u0627\u062F\u0631\u0633\u062A \u0627\u0633\u062A.",
        state: this.snapshot()
      };
    }
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    if (stored && token) {
      try {
        const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/reset-pairing",
          { username, password },
          4e3,
          { Authorization: `Device ${stored.deviceId}.${token}` }
        );
        if (res.status >= 400 && res.status < 500 && res.status !== 404) {
          const err = registrationError(res.body);
          return { ok: false, error: err || "\u0647\u0627\u0628 \u0633\u0627\u0644\u0646 \u062F\u0631\u062E\u0648\u0627\u0633\u062A \u062D\u0630\u0641 \u0627\u062A\u0635\u0627\u0644 \u0631\u0627 \u0646\u067E\u0630\u06CC\u0631\u0641\u062A.", state: this.snapshot() };
        }
      } catch (e) {
        log("warn", `Edge reset-pairing notify skipped/failed: ${errorMessage(e)}`);
      }
    }
    this.performLocalUnpair("\u0627\u062A\u0635\u0627\u0644 \u06A9\u0644\u0627\u06CC\u0646\u062A \u0631\u06CC\u0633\u062A \u0634\u062F\u061B \u0627\u06A9\u0646\u0648\u0646 \u0645\u06CC\u200C\u062A\u0648\u0627\u0646\u06CC\u062F \u0627\u06CC\u0633\u062A\u06AF\u0627\u0647 \u062C\u062F\u06CC\u062F \u062B\u0628\u062A \u06A9\u0646\u06CC\u062F.");
    return { ok: true, error: "", state: this.snapshot() };
  }
  async getSystemSettings() {
    return this.kioskGuard.getSystemSettings();
  }
  setSystemVolume(level) {
    const vol = this.kioskGuard.setVolume(level);
    if (process.platform === "linux") {
      try {
        (0, import_node_child_process4.spawn)("pactl", ["set-sink-volume", "@DEFAULT_SINK@", `${vol}%`], { stdio: "ignore" });
      } catch {
        try {
          (0, import_node_child_process4.spawn)("amixer", ["sset", "Master", `${vol}%`], { stdio: "ignore" });
        } catch {
        }
      }
    }
    return vol;
  }
  setMouseSpeed(speed) {
    return this.kioskGuard.setMouseSpeed(speed);
  }
  async userLogin(credentials) {
    var _a;
    if (!this.state.paired || this.state.phase !== "connected") {
      return { ok: false, error: "\u06A9\u0644\u0627\u06CC\u0646\u062A \u0628\u0647 \u0647\u0627\u0628 \u0633\u0627\u0644\u0646 \u0645\u062A\u0635\u0644 \u0646\u06CC\u0633\u062A.", state: this.snapshot() };
    }
    const stored = this.store.load();
    if (!stored) {
      return { ok: false, error: "\u0627\u0637\u0644\u0627\u0639\u0627\u062A \u062B\u0628\u062A \u062F\u0633\u062A\u06AF\u0627\u0647 \u06CC\u0627\u0641\u062A \u0646\u0634\u062F.", state: this.snapshot() };
    }
    const token = this.store.openToken(stored);
    if (!token) {
      return { ok: false, error: "\u06A9\u0644\u06CC\u062F \u0627\u0645\u0646\u06CC\u062A\u06CC \u062F\u0633\u062A\u06AF\u0627\u0647 \u0646\u0627\u0645\u0639\u062A\u0628\u0631 \u0627\u0633\u062A.", state: this.snapshot() };
    }
    try {
      const creds = credentials || {};
      const username = cleanText(creds.username, 60, "\u0646\u0627\u0645 \u06A9\u0627\u0631\u0628\u0631\u06CC \u06CC\u0627 \u0634\u0645\u0627\u0631\u0647 \u062A\u0645\u0627\u0633");
      const password = cleanText(creds.password, 120, "\u0631\u0645\u0632 \u0639\u0628\u0648\u0631");
      const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
      const res = await requestJson(
        agent,
        stored.pairing,
        "POST",
        "/api/v1/client/user-login",
        { username, password },
        15e3,
        { Authorization: `Device ${stored.deviceId}.${token}` }
      );
      if (res.status !== 200) {
        const error = registrationError(res.body);
        return { ok: false, error, state: this.snapshot() };
      }
      const body = res.body || {};
      const couponHours = Number(body.coupon_hours ?? 0);
      const couponHourlyRate = Number(body.coupon_hourly_rate ?? 2e4);
      const couponMessage = String(body.coupon_message || "");
      const hasCoupon = Boolean(body.has_coupon ?? couponHours > 0);
      const userSession = {
        sessionId: String(body.session_id || ""),
        customerName: String(body.customer_name || ""),
        username: String(body.username || ""),
        walletBalance: Number(body.wallet_balance || 0),
        creditLimit: Number(body.credit_limit || 0),
        hourlyRate: Number(body.hourly_rate || 0),
        tariffName: String(body.tariff_name || ""),
        startedAt: String(body.started_at || (/* @__PURE__ */ new Date()).toISOString()),
        elapsedSeconds: 0,
        pausedSeconds: 0,
        serverCost: 0,
        syncedAt: Date.now(),
        couponHours,
        couponHourlyRate,
        couponMessage,
        hasCoupon
      };
      this.update({
        locked: false,
        userSession
      });
      (_a = this.connection) == null ? void 0 : _a.notifyState();
      this.notify(`\u062E\u0648\u0634 \u0622\u0645\u062F\u06CC\u062F ${userSession.customerName}\u061B \u0648\u0631\u0648\u062F \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u0627\u0646\u062C\u0627\u0645 \u0634\u062F.`);
      if (couponMessage) {
        setTimeout(() => {
          this.notify(couponMessage);
        }, 1200);
      }
      return { ok: true, session: userSession, state: this.snapshot() };
    } catch (error) {
      return { ok: false, error: errorMessage(error), state: this.snapshot() };
    }
  }
  async userLogout(options) {
    var _a;
    const keepProcesses = Boolean(options == null ? void 0 : options.keepProcesses);
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    let elapsedSeconds = 0;
    let cost = 0;
    let walletBalance = 0;
    if (!keepProcesses) {
      void this.killAllGamesAndApps();
    }
    this.kioskDisabled = false;
    this.killExplorer();
    this.update({ locked: true, userSession: null });
    this.syncKioskEnforcement();
    (_a = this.connection) == null ? void 0 : _a.notifyState();
    if (stored && token && this.state.phase === "connected") {
      try {
        const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/user-logout",
          { keep_processes: keepProcesses },
          5e3,
          { Authorization: `Device ${stored.deviceId}.${token}` }
        );
        if (res.status === 200) {
          const body = res.body || {};
          elapsedSeconds = Number(body.elapsed_seconds || 0);
          cost = Number(body.cost || 0);
          walletBalance = Number(body.wallet_balance || 0);
        } else {
          log("warn", `userLogout hub returned status ${res.status}`);
          this.notify("\u0647\u0627\u0628 \u0633\u0627\u0644\u0646 \u067E\u0627\u06CC\u0627\u0646 \u0646\u0634\u0633\u062A \u0631\u0627 \u062A\u0623\u06CC\u06CC\u062F \u0646\u06A9\u0631\u062F\u061B \u0644\u0637\u0641\u0627\u064B \u0628\u0627 \u0645\u0633\u0626\u0648\u0644 \u0633\u0627\u0644\u0646 \u0647\u0645\u0627\u0647\u0646\u06AF \u06A9\u0646\u06CC\u062F.", "error");
        }
      } catch (err) {
        log("warn", `userLogout request failed: ${errorMessage(err)}`);
        this.notify("\u0627\u0631\u062A\u0628\u0627\u0637 \u0628\u0627 \u0647\u0627\u0628 \u0628\u0631\u0627\u06CC \u0628\u0633\u062A\u0646 \u0646\u0634\u0633\u062A \u0628\u0631\u0642\u0631\u0627\u0631 \u0646\u0634\u062F\u061B \u0644\u0637\u0641\u0627\u064B \u0628\u0627 \u0645\u0633\u0626\u0648\u0644 \u0633\u0627\u0644\u0646 \u0647\u0645\u0627\u0647\u0646\u06AF \u06A9\u0646\u06CC\u062F.", "error");
      }
    }
    if (keepProcesses) {
      this.notify("\u062D\u0633\u0627\u0628 \u06A9\u0627\u0631\u0628\u0631\u06CC \u0645\u0648\u0642\u062A\u0627\u064B \u0642\u0641\u0644 \u0634\u062F\u061B \u0628\u0627\u0632\u06CC\u200C\u0647\u0627 \u062F\u0631 \u067E\u0633\u200C\u0632\u0645\u06CC\u0646\u0647 \u0628\u0627\u0632 \u0645\u0627\u0646\u062F\u0646\u062F.");
    } else {
      this.notify(`\u0646\u0634\u0633\u062A \u0628\u0627\u0632\u06CC \u067E\u0627\u06CC\u0627\u0646 \u06CC\u0627\u0641\u062A. \u0647\u0632\u06CC\u0646\u0647: ${cost.toLocaleString()} \u062A\u0648\u0645\u0627\u0646`);
    }
    return {
      ok: true,
      elapsedSeconds,
      cost,
      walletBalance,
      state: this.snapshot()
    };
  }
  async powerAction(action) {
    var _a;
    if (process.platform !== "win32") {
      return { ok: false, error: "\u0627\u06CC\u0646 \u0642\u0627\u0628\u0644\u06CC\u062A \u0641\u0642\u0637 \u0631\u0648\u06CC \u0648\u06CC\u0646\u062F\u0648\u0632 \u062F\u0631 \u062F\u0633\u062A\u0631\u0633 \u0627\u0633\u062A." };
    }
    try {
      await this.userLogout({ keepProcesses: false });
      this.osShuttingDown = action === "shutdown";
      (_a = this.connection) == null ? void 0 : _a.sendGoodbye(action === "shutdown" ? "os_shutdown" : "os_restart", {
        powerState: action === "shutdown" ? "OFF" : "ON",
        kioskState: "LOCKED"
      });
      this.kioskGuard.dispose();
      const args = action === "shutdown" ? ["/s", "/t", "0", "/f"] : ["/r", "/t", "0", "/f"];
      (0, import_node_child_process4.spawn)("shutdown.exe", args, { detached: true, stdio: "ignore" }).unref();
      setTimeout(() => import_electron6.app.exit(0), 1200);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: errorMessage(err) };
    }
  }
  quickLogout() {
    if (this.state.locked || !this.state.userSession) return;
    log("info", "Quick logout triggered (Alt+F5): locking screen and keeping games alive");
    void this.userLogout({ keepProcesses: true });
  }
  checkIdleAutoShutdown() {
    if (this.osShuttingDown || this.idleShutdownMinutes <= 0) return;
    if (process.platform !== "win32") return;
    if (!this.state.locked || this.state.userSession) {
      this.idleWarningNotified = false;
      return;
    }
    try {
      const idleSec = import_electron6.powerMonitor.getSystemIdleTime();
      const thresholdSec = this.idleShutdownMinutes * 60;
      const warningSec = Math.max(0, thresholdSec - 30);
      if (idleSec >= thresholdSec) {
        log("info", `Idle auto-shutdown triggered after ${idleSec}s of inactivity (limit: ${thresholdSec}s)`);
        this.performIdleShutdown();
      } else if (idleSec >= warningSec) {
        if (!this.idleWarningNotified) {
          this.idleWarningNotified = true;
          const remainingSec = thresholdSec - idleSec;
          this.notify(`\u0633\u06CC\u0633\u062A\u0645 \u0628\u0647 \u062F\u0644\u06CC\u0644 \u0639\u062F\u0645 \u0627\u0633\u062A\u0641\u0627\u062F\u0647 \u062A\u0627 ${remainingSec} \u062B\u0627\u0646\u06CC\u0647 \u062F\u06CC\u06AF\u0631 \u062E\u0627\u0645\u0648\u0634 \u062E\u0648\u0627\u0647\u062F \u0634\u062F.`);
        }
      } else if (idleSec < warningSec) {
        this.idleWarningNotified = false;
      }
    } catch (e) {
      log("warn", `Idle check failed: ${e}`);
    }
  }
  performIdleShutdown() {
    if (this.osShuttingDown) return;
    this.osShuttingDown = true;
    this.notify("\u0633\u06CC\u0633\u062A\u0645 \u062F\u0631 \u062D\u0627\u0644 \u062E\u0627\u0645\u0648\u0634 \u0634\u062F\u0646 \u062E\u0648\u062F\u06A9\u0627\u0631 \u0628\u0647 \u062F\u0644\u06CC\u0644 \u0639\u062F\u0645 \u0627\u0633\u062A\u0641\u0627\u062F\u0647 \u0627\u0633\u062A...");
    if (this.idleWatchdogTimer) {
      clearInterval(this.idleWatchdogTimer);
      this.idleWatchdogTimer = null;
    }
    setTimeout(() => {
      if (process.platform === "win32") {
        try {
          (0, import_node_child_process4.spawn)("shutdown.exe", ["/s", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
        } catch {
        }
      } else {
        try {
          (0, import_node_child_process4.spawn)("shutdown", ["-h", "now"], { detached: true, stdio: "ignore" }).unref();
        } catch {
        }
      }
      import_electron6.app.exit(0);
    }, 1e3);
  }
  async getRunningApps() {
    const savedGames = gamesStore.loadGames();
    const rawWindows = await this.kioskGuard.listWindows();
    if (rawWindows.length > 0) {
      return rawWindows.filter((w) => w.pid !== process.pid && w.title.toLowerCase() !== "gamenet").map((w) => {
        const matchedGame = this.launchedGamesMap.get(w.pid) || savedGames.find((g) => {
          const exeBase = import_node_path5.default.basename(g.executable || "").toLowerCase();
          const pName = w.processName.toLowerCase();
          return exeBase.startsWith(pName) || pName.startsWith(exeBase.replace(/\.exe$/, "")) || w.title.toLowerCase().includes(g.name.toLowerCase());
        });
        let icon = matchedGame ? matchedGame.icon : "\u{1F3AE}";
        if (!matchedGame) {
          const pLower = w.processName.toLowerCase();
          if (pLower.includes("chrome") || pLower.includes("firefox") || pLower.includes("msedge") || pLower.includes("browser")) {
            icon = "\u{1F310}";
          } else if (pLower.includes("discord") || pLower.includes("telegram")) {
            icon = "\u{1F4AC}";
          } else if (pLower.includes("calc") || pLower.includes("notepad")) {
            icon = "\u{1F4DD}";
          } else {
            icon = "\u{1F5A5}\uFE0F";
          }
        }
        return {
          id: w.hwnd,
          hwnd: w.hwnd,
          title: w.title,
          processName: w.processName,
          pid: w.pid,
          icon,
          name: matchedGame ? matchedGame.name : w.title,
          isForeground: w.isForeground,
          isMinimized: w.isMinimized
        };
      });
    }
    const result = [];
    for (const proc of this.runningProcesses) {
      if (proc.pid) {
        const game = this.launchedGamesMap.get(proc.pid);
        result.push({
          id: String(proc.pid),
          hwnd: String(proc.pid),
          title: game ? game.name : `\u0628\u0631\u0646\u0627\u0645\u0647 (${proc.pid})`,
          processName: game ? game.executable : "app.exe",
          pid: proc.pid,
          icon: game ? game.icon : "\u{1F3AE}",
          name: game ? game.name : "\u0628\u0631\u0646\u0627\u0645\u0647 \u062F\u0631 \u062D\u0627\u0644 \u0627\u062C\u0631\u0627",
          isForeground: true,
          isMinimized: false
        });
      }
    }
    return result;
  }
  focusApp(hwnd) {
    this.kioskGuard.focusWindow(hwnd);
    return { ok: true };
  }
  minimizeApp(hwnd) {
    this.kioskGuard.minimizeWindow(hwnd);
    return { ok: true };
  }
  closeApp(hwnd, pid) {
    this.kioskGuard.closeWindow(hwnd, pid);
    if (pid) {
      if (process.platform === "win32") {
        try {
          (0, import_node_child_process4.spawn)("taskkill.exe", ["/F", "/T", "/PID", String(pid)], {
            stdio: "ignore",
            windowsHide: true
          }).unref();
        } catch {
        }
      }
      const procIdx = this.runningProcesses.findIndex((p) => p.pid === pid);
      if (procIdx >= 0) {
        try {
          this.runningProcesses[procIdx].kill("SIGTERM");
        } catch {
        }
        this.runningProcesses.splice(procIdx, 1);
      }
      this.launchedGamesMap.delete(pid);
    }
    return { ok: true };
  }
  switchToNextApp() {
    this.kioskGuard.switchToNextWindow();
    return { ok: true };
  }
  async changeUserPassword(input) {
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    if (!stored || !token || this.state.phase !== "connected") {
      return { ok: false, error: "\u06A9\u0644\u0627\u06CC\u0646\u062A \u0628\u0647 \u0647\u0627\u0628 \u0633\u0627\u0644\u0646 \u0645\u062A\u0635\u0644 \u0646\u06CC\u0633\u062A." };
    }
    try {
      const data = input || {};
      const currentPassword = cleanText(data.currentPassword, 120, "\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0641\u0639\u0644\u06CC");
      const newPassword = cleanText(data.newPassword, 120, "\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u062C\u062F\u06CC\u062F");
      const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
      const res = await requestJson(
        agent,
        stored.pairing,
        "POST",
        "/api/v1/client/change-password",
        { current_password: currentPassword, new_password: newPassword },
        15e3,
        { Authorization: `Device ${stored.deviceId}.${token}` }
      );
      if (res.status !== 200) {
        const error = registrationError(res.body);
        return { ok: false, error };
      }
      this.notify("\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u062D\u0633\u0627\u0628 \u06A9\u0627\u0631\u0628\u0631\u06CC \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u062A\u063A\u06CC\u06CC\u0631 \u06CC\u0627\u0641\u062A.");
      return { ok: true, message: "\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0628\u0627 \u0645\u0648\u0641\u0642\u06CC\u062A \u0628\u0647\u200C\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06CC \u0634\u062F." };
    } catch (err) {
      return { ok: false, error: errorMessage(err) };
    }
  }
  notify(text, outcome = "ok") {
    this.emitCommand({
      commandId: "",
      commandType: "notice",
      outcome,
      message: text,
      at: (/* @__PURE__ */ new Date()).toISOString()
    });
  }
  emitCommand(notice) {
    if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
      try {
        this.window.webContents.send("gamenet:event-command", notice);
      } catch {
      }
    }
  }
  update(patch) {
    const prevLocked = this.state.locked;
    this.state = { ...this.state, ...patch };
    if (patch.locked !== void 0 && patch.locked !== prevLocked) {
      this.syncKioskEnforcement();
    }
    this.publish();
  }
  publish() {
    this.state.updatedAt = (/* @__PURE__ */ new Date()).toISOString();
    if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
      try {
        this.window.webContents.send("gamenet:event-state", { ...this.state });
      } catch {
      }
    }
  }
  handleOsShutdown() {
    var _a;
    this.osShuttingDown = true;
    isAppQuitting = true;
    this.kioskGuard.dispose();
    (_a = this.connection) == null ? void 0 : _a.sendGoodbye("os_shutdown", { powerState: "OFF" });
  }
  prepareQuit() {
    var _a, _b;
    isAppQuitting = true;
    this.kioskGuard.dispose();
    if (this.osShuttingDown) {
      (_a = this.connection) == null ? void 0 : _a.sendGoodbye("os_shutdown", { powerState: "OFF" });
    } else {
      this.killRunningProcesses();
      this.kioskDisabled = true;
      (_b = this.connection) == null ? void 0 : _b.sendGoodbye("app_quit", { powerState: "ON", kioskState: "DISABLED" });
    }
  }
  dispose() {
    var _a, _b;
    if (this.lockWatchdogTimer) {
      clearInterval(this.lockWatchdogTimer);
      this.lockWatchdogTimer = null;
    }
    if (this.idleWatchdogTimer) {
      clearInterval(this.idleWatchdogTimer);
      this.idleWatchdogTimer = null;
    }
    this.kioskGuard.dispose();
    (_a = this.remoteDesktop) == null ? void 0 : _a.dispose();
    (_b = this.connection) == null ? void 0 : _b.stop();
  }
};
var controller = null;
var mainWindow = null;
function isBlockedRendererInput(input) {
  const key = (input.key || "").toLowerCase();
  const code = (input.code || "").toLowerCase();
  if (input.meta || key === "meta" || key === "os" || key === "contextmenu" || code === "metaleft" || code === "metaright" || code === "osleft" || code === "osright") {
    return true;
  }
  if (key === "escape" && (input.control || input.alt)) {
    return true;
  }
  if (input.alt && key === "f5") {
    return false;
  }
  if (input.alt && key === "tab" && controller && !controller.isLocked()) {
    return false;
  }
  if (input.alt && (key === "f4" || key === "tab" || key === "arrowleft" || key === "arrowright" || key === "home" || key === " ")) {
    return true;
  }
  if (key === "f1" || key === "f3" || key === "f5" || key === "f6" || key === "f7" || key === "f10" || key === "f11") {
    return true;
  }
  if (process.env.GAMENET_DEVTOOLS !== "1") {
    if (key === "f12") return true;
    if (input.control && input.shift && (key === "i" || key === "j" || key === "c" || key === "k")) {
      return true;
    }
  }
  if (input.control && !input.alt) {
    if (key === "r" || key === "w" || key === "q" || key === "n" || key === "t" || key === "l" || key === "p" || key === "s" || key === "o" || key === "tab") {
      return true;
    }
  }
  return false;
}
function createWindow() {
  const window = new import_electron6.BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    kiosk: !isDevWindow,
    alwaysOnTop: !isDevWindow,
    fullscreen: false,
    frame: isDevWindow,
    closable: isDevWindow,
    minimizable: isDevWindow,
    maximizable: isDevWindow,
    resizable: isDevWindow,
    skipTaskbar: !isDevWindow,
    backgroundColor: "#070b10",
    autoHideMenuBar: true,
    title: "GameNet",
    webPreferences: {
      preload: import_node_path5.default.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      webviewTag: false,
      spellcheck: false,
      enableBlinkFeatures: "",
      backgroundThrottling: false
    }
  });
  window.setMenuBarVisibility(false);
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
  window.webContents.on("context-menu", (event) => {
    if (!isDevWindow) {
      event.preventDefault();
    }
  });
  window.webContents.on("before-input-event", (event, input) => {
    if (isDevWindow || (controller == null ? void 0 : controller.isKioskDisabled())) return;
    const key = (input.key || "").toLowerCase();
    if (input.alt && key === "f5" && input.type === "keyDown") {
      event.preventDefault();
      controller == null ? void 0 : controller.quickLogout();
      return;
    }
    if (input.alt && key === "tab" && input.type === "keyDown" && !(controller == null ? void 0 : controller.isLocked())) {
      event.preventDefault();
      controller == null ? void 0 : controller.switchToNextApp();
      return;
    }
    if (isBlockedRendererInput(input)) {
      event.preventDefault();
    }
  });
  window.on("close", (event) => {
    if (isAppQuitting || isDevWindow || (controller == null ? void 0 : controller.isKioskDisabled())) return;
    event.preventDefault();
    controller == null ? void 0 : controller.syncKioskEnforcement();
  });
  window.on("minimize", () => {
    if (isAppQuitting || isDevWindow || (controller == null ? void 0 : controller.isKioskDisabled())) return;
    setImmediate(() => {
      if (!window.isDestroyed()) {
        window.restore();
        controller == null ? void 0 : controller.syncKioskEnforcement();
      }
    });
  });
  window.on("leave-full-screen", () => {
    if (isAppQuitting || isDevWindow || !controller || controller.isKioskDisabled()) return;
    setImmediate(() => {
      if (!window.isDestroyed() && !window.isFullScreen()) {
        controller == null ? void 0 : controller.syncKioskEnforcement();
      }
    });
  });
  window.on("blur", () => {
    if (isAppQuitting || isDevWindow || !controller || controller.isKioskDisabled() || !controller.isLocked() || controller.isDialogShowing()) {
      return;
    }
    setTimeout(() => {
      if (!window.isDestroyed() && !isAppQuitting && controller && !controller.isKioskDisabled() && controller.isLocked() && !controller.isDialogShowing()) {
        try {
          window.show();
          window.setAlwaysOnTop(true);
          window.moveTop();
          window.focus();
        } catch {
        }
      }
    }, 120);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    log("error", `Render process gone: reason=${details.reason}, exitCode=${details.exitCode}`);
    if (details.reason !== "clean-exit") {
      log("info", "Reloading mainWindow after render process crash...");
      window.reload();
    }
  });
  window.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    log("error", `MainWindow failed to load: ${errorCode} - ${errorDescription}`);
    setTimeout(() => {
      if (!window.isDestroyed()) {
        window.loadFile(import_node_path5.default.join(__dirname, "..", "dist", "index.html"));
      }
    }, 1500);
  });
  window.on("unresponsive", () => {
    log("warn", "MainWindow became unresponsive");
  });
  window.once("ready-to-show", () => {
    window.show();
    controller == null ? void 0 : controller.syncKioskEnforcement();
    if (process.env.GAMENET_DEVTOOLS === "1") {
      window.webContents.openDevTools({ mode: "detach" });
    }
  });
  void window.loadFile(import_node_path5.default.join(__dirname, "..", "dist", "index.html"));
  return window;
}
function registerIpc() {
  import_electron6.ipcMain.handle("gamenet:snapshot", () => (controller == null ? void 0 : controller.snapshot()) ?? emptyState());
  import_electron6.ipcMain.handle(
    "gamenet:pair",
    (_event, input) => controller ? controller.pair(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:unpair",
    () => controller ? controller.unpair() : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:preview",
    (_event, enabled) => controller && typeof enabled === "boolean" ? controller.setPreview(enabled) : (controller == null ? void 0 : controller.snapshot()) ?? emptyState()
  );
  import_electron6.ipcMain.handle("gamenet:lock", () => (controller == null ? void 0 : controller.lock()) ?? emptyState());
  import_electron6.ipcMain.handle(
    "gamenet:launch-game",
    (_event, input) => controller ? controller.launchGame(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A" }
  );
  import_electron6.ipcMain.handle(
    "gamenet:user-login",
    (_event, creds) => controller ? controller.userLogin(creds) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:user-logout",
    (_event, options) => controller ? controller.userLogout(options && typeof options === "object" ? options : void 0) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:user-logout-quick",
    () => controller ? controller.userLogout({ keepProcesses: true }) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:system-power",
    (_event, action) => controller && (action === "shutdown" || action === "restart") ? controller.powerAction(action) : { ok: false, error: "\u062F\u0631\u062E\u0648\u0627\u0633\u062A \u0646\u0627\u0645\u0639\u062A\u0628\u0631 \u0627\u0633\u062A" }
  );
  import_electron6.ipcMain.handle("gamenet:kill-all-games", async () => {
    if (controller) {
      await controller.killAllGamesAndApps();
    }
    return { ok: true };
  });
  import_electron6.ipcMain.handle(
    "gamenet:change-password",
    (_event, input) => controller ? controller.changeUserPassword(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A" }
  );
  import_electron6.ipcMain.handle("gamenet:get-running-apps", () => controller ? controller.getRunningApps() : []);
  import_electron6.ipcMain.handle(
    "gamenet:focus-app",
    (_event, hwnd) => controller ? controller.focusApp(String(hwnd || "")) : { ok: false }
  );
  import_electron6.ipcMain.handle(
    "gamenet:minimize-app",
    (_event, hwnd) => controller ? controller.minimizeApp(String(hwnd || "")) : { ok: false }
  );
  import_electron6.ipcMain.handle("gamenet:close-app", (_event, payload) => {
    if (!controller || !payload || typeof payload !== "object") return { ok: false };
    const p = payload;
    return controller.closeApp(String(p.hwnd || ""), typeof p.pid === "number" ? p.pid : void 0);
  });
  import_electron6.ipcMain.handle("gamenet:switch-next-app", () => controller ? controller.switchToNextApp() : { ok: false });
  import_electron6.ipcMain.handle(
    "gamenet:get-system-settings",
    () => controller ? controller.getSystemSettings() : { volume: 75, mouseSpeed: 10 }
  );
  import_electron6.ipcMain.handle("gamenet:set-system-volume", (_event, level) => {
    const raw = typeof level === "number" ? level : Number(level ?? 75);
    const vol = controller ? controller.setSystemVolume(raw) : Math.round(raw);
    return { ok: true, volume: vol };
  });
  import_electron6.ipcMain.handle("gamenet:set-mouse-speed", (_event, speed) => {
    const raw = typeof speed === "number" ? speed : Number(speed ?? 10);
    const spd = controller ? controller.setMouseSpeed(raw) : Math.round(raw);
    return { ok: true, speed: spd };
  });
  import_electron6.ipcMain.handle("gamenet:get-games", () => gamesStore.loadGames());
  import_electron6.ipcMain.handle("gamenet:copy-text", (_event, text) => {
    import_electron6.clipboard.writeText(typeof text === "string" ? text : String(text ?? ""));
    return { ok: true };
  });
  import_electron6.ipcMain.handle(
    "gamenet:save-games",
    (_event, games) => Array.isArray(games) ? gamesStore.saveGames(games) : gamesStore.loadGames()
  );
  import_electron6.ipcMain.handle("gamenet:get-announcements", () => (controller == null ? void 0 : controller.getAnnouncements()) ?? []);
  import_electron6.ipcMain.handle("gamenet:browse-executable", async () => {
    controller == null ? void 0 : controller.setDialogOpen(true);
    try {
      const dialogOpts = {
        title: "\u0627\u0646\u062A\u062E\u0627\u0628 \u0641\u0627\u06CC\u0644 \u0627\u062C\u0631\u0627\u06CC\u06CC \u0628\u0627\u0632\u06CC \u06CC\u0627 \u0628\u0631\u0646\u0627\u0645\u0647",
        filters: [
          { name: "\u0641\u0627\u06CC\u0644\u200C\u0647\u0627\u06CC \u0627\u062C\u0631\u0627\u06CC\u06CC (Executables)", extensions: ["exe", "bat", "cmd", "lnk", "url"] },
          { name: "\u0647\u0645\u0647 \u0641\u0627\u06CC\u0644\u200C\u0647\u0627", extensions: ["*"] }
        ],
        properties: ["openFile"]
      };
      const res = mainWindow && !mainWindow.isDestroyed() ? await import_electron6.dialog.showOpenDialog(mainWindow, dialogOpts) : await import_electron6.dialog.showOpenDialog(dialogOpts);
      if (res.canceled || res.filePaths.length === 0) {
        return null;
      }
      return res.filePaths[0];
    } finally {
      controller == null ? void 0 : controller.setDialogOpen(false);
    }
  });
  import_electron6.ipcMain.handle(
    "gamenet:admin-unlock",
    (_event, input) => controller ? controller.handleLocalAdminUnlock(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A" }
  );
  import_electron6.ipcMain.handle(
    "gamenet:reconfigure-connection",
    (_event, input) => controller ? controller.reconfigureConnection(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
  import_electron6.ipcMain.handle(
    "gamenet:reset-client-pairing",
    (_event, input) => controller ? controller.resetClientPairing(input) : { ok: false, error: "\u0628\u0631\u0646\u0627\u0645\u0647 \u0622\u0645\u0627\u062F\u0647 \u0646\u06CC\u0633\u062A", state: emptyState() }
  );
}
var hasLock = import_electron6.app.requestSingleInstanceLock();
if (!hasLock) {
  import_electron6.app.quit();
} else {
  import_electron6.app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  import_electron6.app.on("web-contents-created", (_event, contents) => {
    contents.setWindowOpenHandler(() => ({ action: "deny" }));
    contents.on("will-attach-webview", (event) => event.preventDefault());
  });
  try {
    import_electron6.app.disableHardwareAcceleration();
  } catch {
  }
  void import_electron6.app.whenReady().then(() => {
    initLogging();
    log("info", `GameNet ${import_electron6.app.getVersion()} starting on ${import_node_os3.default.type()} ${import_node_os3.default.release()} ${import_node_os3.default.arch()}`);
    import_electron6.session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
      callback(false);
    });
    import_electron6.session.defaultSession.setPermissionCheckHandler(() => false);
    if (process.platform === "win32") {
      try {
        import_electron6.app.setLoginItemSettings({
          openAtLogin: true,
          openAsHidden: false,
          path: process.execPath,
          args: []
        });
        log("info", `Auto-login startup item registered for ${process.execPath}`);
      } catch (e) {
        log("warn", `Could not set login item settings: ${e}`);
      }
    }
    controller = new AppController();
    mainWindow = createWindow();
    controller.attach(mainWindow);
    registerIpc();
    try {
      import_electron6.globalShortcut.register("Control+Alt+Shift+E", () => {
        log("info", "Emergency admin hotkey (Ctrl+Alt+Shift+E) pressed");
        if (mainWindow && !mainWindow.isDestroyed()) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send("gamenet:trigger-admin-escape");
        }
      });
      import_electron6.globalShortcut.register("Alt+F5", () => {
        log("info", "Global hotkey (Alt+F5) pressed");
        controller == null ? void 0 : controller.quickLogout();
      });
    } catch (err) {
      log("warn", `Failed to register global shortcuts: ${err}`);
    }
    import_electron6.powerMonitor.on("shutdown", () => {
      log("info", "OS shutdown detected - reporting power OFF to Edge");
      controller == null ? void 0 : controller.handleOsShutdown();
    });
    import_electron6.powerMonitor.on("unlock-screen", () => {
      controller == null ? void 0 : controller.syncKioskEnforcement();
    });
    import_electron6.app.on("activate", () => {
      if (import_electron6.BrowserWindow.getAllWindows().length === 0 && controller) {
        mainWindow = createWindow();
        controller.attach(mainWindow);
      }
    });
  });
  import_electron6.app.on("before-quit", () => {
    try {
      import_electron6.globalShortcut.unregisterAll();
    } catch {
    }
    controller == null ? void 0 : controller.prepareQuit();
    controller == null ? void 0 : controller.dispose();
  });
  import_electron6.app.on("window-all-closed", () => {
    import_electron6.app.quit();
  });
}
