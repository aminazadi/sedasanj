/*
 * gsm-encode.c - minimal GSM 06.10 full-rate encoder front end.
 *
 * Reads raw headerless 16-bit signed little-endian mono PCM samples
 * from stdin (8000 Hz expected - GSM 06.10 is defined at that rate)
 * and writes raw concatenated 33-byte GSM frames to stdout: no file
 * header, no "toast" magic-byte wrapper file - just back-to-back
 * gsm_encode() output, which is exactly the on-disk shape Asterisk's
 * own format_gsm module reads/writes (Asterisk uses this same
 * public-domain GSM 06.10 reference implementation internally, under
 * codecs/gsm/).
 *
 * Each 33-byte frame already carries libgsm's own per-frame framing
 * (the GSM_MAGIC nibble is baked in by gsm_encode() itself), so no
 * extra container is needed on top - this has been verified to
 * produce byte-identical output to `toast -l -c` (the gsm-utils /
 * libgsm-tools package's CLI) on the same raw input.
 *
 * Links against libgsm (MIT-licensed, Jutta Degener & Carsten Bormann,
 * Technische Universitaet Berlin - the same GSM 06.10 reference
 * implementation Asterisk vendors and the same library "toast" wraps).
 * See http://www.quut.com/gsm/ for the original source distribution.
 *
 * Build (on a box of the target architecture, or cross-compiled):
 *   apt-get install -y libgsm1-dev
 *   gcc -O2 -Wall -Wextra -static -o gsm-encode-<arch> gsm-encode.c -lgsm
 *   strip gsm-encode-<arch>
 * Place the result at bin/gsm/gsm-encode-<arch> (arch = x86_64 or
 * aarch64, matching php_uname('m') via Staging::archTag()) - see
 * build.sh in this directory for a ready-made version of the above.
 */

#include <gsm.h>
#include <stdio.h>
#include <string.h>

#define FRAME_SAMPLES 160
#define FRAME_BYTES   (FRAME_SAMPLES * 2)
#define GSM_FRAME_BYTES 33

int main(void)
{
    gsm handle = gsm_create();
    if (!handle) {
        fprintf(stderr, "gsm-encode: gsm_create() failed\n");
        return 1;
    }

    unsigned char inbuf[FRAME_BYTES];
    gsm_signal samples[FRAME_SAMPLES];
    gsm_byte outframe[GSM_FRAME_BYTES];
    size_t framesEncoded = 0;

    for (;;) {
        size_t got = fread(inbuf, 1, FRAME_BYTES, stdin);
        if (got == 0) {
            break;
        }
        if (got < FRAME_BYTES) {
            /* Zero-pad the final partial frame (silence) so every
               frame is a full 160 samples - GSM 06.10 has a fixed
               20ms frame size, it can't encode a partial one. */
            memset(inbuf + got, 0, FRAME_BYTES - got);
        }

        for (int i = 0; i < FRAME_SAMPLES; i++) {
            unsigned int lo = inbuf[i * 2];
            unsigned int hi = inbuf[i * 2 + 1];
            short v = (short) ((hi << 8) | lo);
            samples[i] = (gsm_signal) v;
        }

        gsm_encode(handle, samples, outframe);

        if (fwrite(outframe, 1, GSM_FRAME_BYTES, stdout) != GSM_FRAME_BYTES) {
            fprintf(stderr, "gsm-encode: write error\n");
            gsm_destroy(handle);
            return 1;
        }
        framesEncoded++;

        if (got < FRAME_BYTES) {
            break; /* final (padded) frame handled */
        }
    }

    gsm_destroy(handle);

    if (framesEncoded == 0) {
        fprintf(stderr, "gsm-encode: no input samples read\n");
        return 1;
    }

    return 0;
}
