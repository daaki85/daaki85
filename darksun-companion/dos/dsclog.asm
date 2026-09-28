; DSCLOG.EXE - dice log helper for the Dark Sun companion.
;
; A tiny TSR that stays resident (load it high with LH) and holds a ring
; buffer plus a replacement for the game's Borland rand(). The companion runs a
; patched copy of the game (DSUNLOG.EXE) whose rand() and two "probe" places
; start with INT instructions; this TSR answers those interrupts
; (VEC_RAND, VEC_SAVE, VEC_AC) and the companion reads the ring buffer from
; DOSBox's memory.
;
; STUB produces exactly the numbers the original rand() would
; (seed = seed * 0x015A4E35 + 1, result = (seed >> 16) & 0x7FFF), so the game
; plays the same. For every call it also records who called and the caller's
; stack frame, which holds the dice size, THAC0, target AC and so on.
;
; It is a small .EXE rather than a .COM so that LH can load it into upper
; memory: a .COM asks DOS for a whole 64 KB block, more than DOSBox's UMB has.
;
; Build: nasm -f bin -o DSCLOG.EXE dsclog.asm

BITS 16
CPU 386

VEC_RAND equ 0x60     ; rand() (DSUNLOG.EXE: INT 60h at the start of rand())
VEC_SAVE equ 0x61     ; PROBE_SAVE
VEC_AC   equ 0x62     ; PROBE_AC

NENT    equ 128         ; entries in the ring
ESIZE   equ 192         ; bytes per entry (see ENTRY LAYOUT)
STACK   equ 256         ; bytes of stack while installing

; ---- MZ header: no relocations, and only as much memory as the image needs ----
section mz start=0
        db 'MZ'
        dw file_len % 512                       ; bytes in the last page
        dw (file_len + 511) / 512               ; pages
        dw 0                                    ; relocations
        dw 2                                    ; header size in paragraphs
        dw STACK / 16                           ; min extra paragraphs
        dw STACK / 16                           ; max extra paragraphs
        dw 0                                    ; SS (relative to the image)
        dw image_len + STACK                    ; SP
        dw 0                                    ; checksum
        dw install                              ; IP
        dw 0                                    ; CS (relative to the image)
        dw 0x1C                                 ; relocation table offset
        dw 0                                    ; overlay
        align 32, db 0

section image follows=mz vstart=0

; ---- header, found by the companion via SIG (16-byte aligned) ----
hdr:
sig      db 'DSCLOGv5'          ; +0
seq      dw 0                   ; +8   entries written so far (wraps at 65536)
widx     dw 0                   ; +10  ring slot the next entry goes to
nent     dw NENT                ; +12
esize    dw ESIZE               ; +14
ring_off dw ring                ; +16  offset of the ring in this segment
stub_off dw stub                ; +18  offset of STUB in this segment
hdr_off  dw hdr                 ; +20  offset of this header in this segment
seed_off dw 0x4122              ; +22  DS offset of the game's 32-bit rand seed
glob     dw 0, 0, 0, 0          ; +24  DS offsets of 4 game words to capture (0 = none)
nfilt    dw NFILT               ; +32  number of filters in use (0 = record every call)
filt:                           ; +34  up to 8 filters: a length (1-8), then that many bytes the
                                ;      calling code must start with to be recorded. By default,
                                ;      "rand()*N/32768" rolls (movsx eax,ax, then N) and the
                                ;      percentile check, so bursts of other randomness
                                ;      (animations) don't crowd out the rolls that matter
        db 7, 0x66,0x0F,0xBF,0xC0,0x66,0x6B,0xC0, 0     ; imul eax,eax,imm8
        db 7, 0x66,0x0F,0xBF,0xC0,0x66,0x69,0xC0, 0     ; imul eax,eax,imm32
        db 7, 0x66,0x0F,0xBF,0xC0,0x66,0xC1,0xE0, 0     ; shl eax,n
        db 8, 0x66,0x0F,0xBF,0xC0,0x66,0x0F,0xBF,0x56   ; N = word [bp+x] (the dice routines)
        db 8, 0xBB,0x64,0x00,0x99,0xF7,0xFB,0x3B,0x56   ; percentile check
NFILT   equ ($ - filt) / 9
        times (8 - NFILT) * 9 db 0
skipped  dw 0                   ; +106 calls not recorded because no filter matched
probe_save_off dw probe_save    ; +108 offset of PROBE_SAVE in this segment
probe_ac_off   dw probe_ac      ; +110 offset of PROBE_AC in this segment
vectors  db VEC_RAND, VEC_SAVE, VEC_AC  ; +112 the interrupts the patched game uses
hooked   db 0                   ; +115 1 once the vectors are ours
int_rand_off dw int_rand        ; +116 offset of INT_RAND (VEC_RAND's handler) in this segment

; ENTRY LAYOUT (ESIZE bytes, all words little-endian)
;   +0  seq of this entry (0xFFFF while being written)
;   +2  caller IP        +4  caller CS
;   +6  rand() result    +8  caller BP     +10 SS    +12 DS
;   +14 parent BP (word at SS:BP, the caller's caller's frame)
;   +16 32 bytes from SS:BP+2   (the caller's return address, then its arguments)
;   +48 32 bytes from SS:parentBP+2 (the same for the caller's caller)
;   +80 the 4 captured game words (glob)
;   +88 16 bytes from SS:BP-10h (the caller's last local variables)
;   +104 24 bytes of code at the caller's return address (overlays move, so
;       the code is copied now rather than read later)
;   +128 16 bytes of code at the return address stored at SS:BP+2 (the
;       caller's own caller)
;   +144 40 bytes from SS:parentBP-28h (the caller's caller's local variables)
;   +184 kind: 0 = a rand() call, 1 = PROBE_SAVE (+6 = total, save value),
;        2 = PROBE_AC (+6 = the AC)
;   +186 PROBE_SAVE: the segment of the game's spell table (0 otherwise)
;
; An entry is complete once the header's seq has counted it: the entry's own
; seq is written before the header's.

; The patched rand() starts with INT VEC_RAND. Drop the interrupt frame (restoring
; the caller's flags, so interrupts are enabled again) and be rand().
int_rand:
        add sp, 4
        popf
stub:
        push eax                ; rand() leaves the upper half of EAX alone; so do we
        push si
        mov si, sp              ; SS:SI+6 = return IP, SS:SI+8 = return CS

        mov bx, [cs:seed_off]   ; DS is the game's data segment here
        mov eax, [bx]
        imul eax, eax, 0x015A4E35
        inc eax
        mov [bx], eax
        shr eax, 16
        cwd                     ; as the original: DX = sign of the high word
        and ax, 0x7FFF

        push ax
        push dx
        push di
        push es
        push cx

        mov cx, [cs:nfilt]      ; only record calls whose calling code matches a filter
        jcxz .record
        push ds
        push si
        push di
        lds si, [ss:si+6]       ; DS:SI = the code after this rand() call
        mov bx, filt
.filter:
        push si
        push cx
        push cs
        pop es
        mov di, bx
        xor cx, cx
        mov cl, [cs:bx]         ; the filter's length
        inc di
        repe cmpsb
        pop cx                  ; POP leaves the flags alone
        pop si
        je .matched
        add bx, 9
        loop .filter
        pop di
        pop si
        pop ds
        inc word [cs:skipped]
        jmp .done
.matched:
        pop di
        pop si
        pop ds

.record:
        mov word [cs:kind], 0
        call record

.done:
        pop cx
        pop es
        pop di
        pop dx
        pop ax
        mov bx, ax              ; BX is scratch for rand() callers
        pop si
        pop eax
        mov ax, bx
        retf


; RECORD: add an entry to the ring.
;   SS:SI+6 = the return address of the call being logged (IP, then CS)
;   BP      = the frame of the code that made that call
;   AX      = the value to store at +6;  [kind] = the entry kind
; Keeps every register except the flags.
record:
        push bx
        push cx
        push di
        push es
        push cs
        pop es
        mov di, [cs:widx]
        imul di, di, ESIZE
        add di, ring
        mov word [es:di], 0xFFFF
        mov cx, [cs:kind]
        mov [es:di+184], cx
        mov cx, [cs:extra]
        mov [es:di+186], cx
        mov word [cs:extra], 0
        mov cx, [ss:si+6]
        mov [es:di+2], cx
        mov cx, [ss:si+8]
        mov [es:di+4], cx
        mov [es:di+6], ax
        mov [es:di+8], bp
        mov [es:di+10], ss
        mov [es:di+12], ds
        mov cx, [bp]            ; BP-relative: SS
        mov [es:di+14], cx

        push ds
        push si
        push ss
        pop ds
        lea si, [bp+2]
        add di, 16
        mov cx, 16
        rep movsw               ; +16..+47
        mov si, [bp]
        add si, 2
        mov cx, 16
        rep movsw               ; +48..+79
        pop si
        pop ds

        xor bx, bx
.glob:
        push bx
        mov bx, [cs:glob+bx]
        xor cx, cx
        or bx, bx
        jz .noglob
        mov cx, [bx]            ; game DS
.noglob:
        mov [es:di], cx
        add di, 2
        pop bx
        add bx, 2
        cmp bx, 8
        jb .glob
        push ds                 ; DI is at +72: the caller's locals
        push si
        push ss
        pop ds
        lea si, [bp-16]
        mov cx, 8
        rep movsw
        pop si
        pop ds

        push ds                 ; DI is at +88: the calling code
        push si
        lds si, [ss:si+6]       ; the return address of this rand() call
        mov cx, 12
        rep movsw
        pop si
        push si
        lds si, [ss:bp+2]       ; the return address in the caller's frame
        mov cx, 8
        rep movsw
        push ss                 ; DI is at +128: the caller's caller's locals
        pop ds
        mov si, [bp]
        sub si, 0x28
        mov cx, 20
        rep movsw
        pop si
        pop ds
        sub di, 184             ; back to the start of the entry

        mov cx, [cs:seq]        ; publish: entry seq first, then the header's
        inc cx
        mov [es:di], cx
        mov [cs:seq], cx
        mov cx, [cs:widx]
        inc cx
        cmp cx, NENT
        jb .slot
        xor cx, cx
.slot:
        mov [cs:widx], cx
        pop es
        pop di
        pop cx
        pop bx
        ret

; PROBE_SAVE: INT VEC_SAVE replaces "mov al,[bp-2] / cmp al,[bp-1]" (6 bytes:
; INT + 4 NOPs) at the end of the saving-throw function, where [bp-2] is the
; final total (d20 + modifiers) and [bp-1] the save value it must reach.
; Records both, then does the replaced instructions; RETF 2 keeps their flags.
probe_save:
        sti
        push si
        mov si, sp
        sub si, 4               ; SS:SI+6 = our return address
        push ax
        push ds
        push bx
        lds bx, [ss:si+6]       ; our return address, 2 bytes after the patch
        mov ax, [bx-SPELL_SEG]  ; the saving throw's "mov ax,<spell table>"
        mov [cs:extra], ax
        pop bx
        pop ds
        mov ax, [bp-2]          ; AL = total, AH = save value
        mov word [cs:kind], 1
        call record
        pop ax
        pop si
        mov al, [bp-2]
        cmp al, [bp-1]
        retf 2

; PROBE_AC: INT VEC_AC replaces "mov ax,[bp-6] / add ax,si" (5 bytes: INT + 3
; NOPs) at the end of the AC function. Does the replaced instructions and
; records the result: the AC the game uses for this attack.
probe_ac:
        sti
        push si                 ; the game's SI is part of the AC
        mov ax, [bp-6]
        add ax, si
        mov si, sp
        sub si, 4
        mov word [cs:kind], 2
        call record
        pop si
        retf 2

kind    dw 0
extra   dw 0
SPELL_SEG equ 2 + 0x79BB7 - 0x79A85  ; return address - (DSUN.EXE offsets: patch, mov ax's operand)

align 16
ring:   times NENT*ESIZE db 0
resident_end:

install:                        ; DS = ES = PSP, CS = the image
        mov [cs:psp], es
        push cs
        pop ds
        mov si, vectors         ; the vectors must be free
        mov cx, 3
.check:
        lodsb
        mov ah, 35h
        int 21h                 ; ES:BX = the vector
        mov dx, es
        or dx, bx
        jz .free
        mov dx, busy
        mov ah, 9
        int 21h
        mov ax, 4C01h
        int 21h
.free:
        loop .check

        mov ax, 2500h + VEC_RAND
        mov dx, int_rand
        int 21h
        mov ax, 2500h + VEC_SAVE
        mov dx, probe_save
        int 21h
        mov ax, 2500h + VEC_AC
        mov dx, probe_ac
        int 21h
        mov byte [hooked], 1

        mov es, [cs:psp]
        mov es, [es:0x2C]       ; free our copy of the environment
        mov ah, 49h
        int 21h
        mov dx, msg
        mov ah, 9
        int 21h
        mov dx, 0x10 + (resident_end - hdr + 15) / 16  ; PSP + resident image, in paragraphs
        mov ax, 3100h
        int 21h

msg     db 'Dark Sun companion dice log helper loaded.', 13, 10, '$'
psp     dw 0
busy    db 'DSCLOG: interrupts 60h-62h are in use (already loaded?). Not loaded.', 13, 10, '$'

        align 16, db 0
image_len equ $ - $$
file_len  equ image_len + 32
