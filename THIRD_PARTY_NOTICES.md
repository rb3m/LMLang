# Third-party notices

The following notices are copied from the indicated source headers, with comment delimiters removed. Each section identifies the LM files derived from that origin.

## Go Authors — BSD-3-Clause

`lm/float_math.py` and `lm/runtime/go/floatmath.go` port the Go math exp/log algorithms (Go 1.27.2).

```text
Copyright 2009 The Go Authors. All rights reserved.
Use of this source code is governed by a BSD-style license.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
* Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
* Neither the name of Google Inc. nor the names of its contributors may be
  used to endorse or promote products derived from this software without
  specific prior written permission.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

## Sun Microsystems — fdlibm / FreeBSD msun

The distinct notice wordings below are retained from the source headers.

### Exponential and logarithm

`lm/float_math.py`, `lm/runtime/go/floatmath.go`.

```text
Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunPro, a Sun Microsystems, Inc. business.
e_log2.c/e_log10.c/k_log.h: Developed at SunSoft, a Sun Microsystems,
Inc. business. Copyright (C) 1993 by Sun Microsystems, Inc.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

### Inverse trigonometry

`lm/float_math_atrig.py`, `lm/runtime/go/floatmath_atrig.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunSoft (asin/acos/atan2) and SunPro (atan),
Sun Microsystems, Inc. businesses.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

### Hyperbolic functions

`lm/float_math_hyp.py`, `lm/runtime/go/floatmath_hyp.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunSoft (sinh/cosh) and SunPro (tanh), Sun Microsystems,
Inc. businesses. Permission to use, copy, modify, and distribute this
software is freely granted, provided that this notice is preserved.
```

### log1p / expm1

`lm/float_math_m1.py`, `lm/runtime/go/floatmath_m1.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunPro, a Sun Microsystems, Inc. business.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

### Power

`lm/float_math_pow.py`, `lm/runtime/go/floatmath_pow.go`.

```text
Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

### Range reduction

`lm/float_math_reduce.py`, `lm/runtime/go/floatmath_reduce.go`, `lm/runtime/go/floatmath_reduce_large.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunSoft, a Sun Microsystems, Inc. business.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
e_rem_pio2 optimized by Bruce D. Evans.
```

### Cube root and hypotenuse

`lm/float_math_roots.py`, `lm/runtime/go/floatmath_roots.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunPro (s_cbrt.c) and SunSoft (e_hypot.c), Sun Microsystems,
Inc. businesses. Permission to use, copy, modify, and distribute this
software is freely granted, provided that this notice is preserved.
s_cbrt.c optimized by Bruce D. Evans.
```

### Trigonometry (Python header)

`lm/float_math_trig.py`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunPro (s_sin/s_cos/s_tan) and SunSoft (k_sin/k_cos),
Sun Microsystems, Inc. businesses.
Copyright 2004 Sun Microsystems, Inc. All Rights Reserved. (k_tan)
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

### Trigonometry (Go header)

`lm/runtime/go/floatmath_trig.go`.

```text
Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
s_sin.c/s_cos.c/s_tan.c: Developed at SunPro, a Sun Microsystems, Inc. business.
k_sin.c/k_cos.c: Developed at SunSoft, a Sun Microsystems, Inc. business.
k_tan.c: Copyright 2004 Sun Microsystems, Inc. All Rights Reserved.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

## David Schultz / FreeBSD — BSD-2-Clause

The `k_exp.c` scaled exponential algorithm is used in `lm/float_math_hyp.py` and `lm/runtime/go/floatmath_hyp.go`. Their headers have distinct disclaimer quotation marks; both forms are reproduced below.

### Python header

```text
k_exp.c: Copyright (c) 2011 David Schultz <das@FreeBSD.ORG>
All rights reserved.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.
```

### Go header

```text
k_exp.c: Copyright (c) 2011 David Schultz <das@FreeBSD.ORG>
All rights reserved.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
 1. Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.
 2. Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS “AS IS” AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.
```

## Unicode data

`lm/unicode_tables.py` is generated by `bench/gen_unicode_tables.py` from Unicode 16.0.0 `UnicodeData.txt`. The Unicode license is reproduced in [licenses/UNICODE-LICENSE-V3.txt](licenses/UNICODE-LICENSE-V3.txt).
