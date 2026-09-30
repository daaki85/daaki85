; DSCLOG.EXE - dice log helper for the Dark Sun companion.
;
; A tiny TSR that stays resident (load it high with LH) and holds a ring
; buffer plus a replacement for the game's Borland rand(). The companion runs a
; patched copy of the game (DSUNLOG.EXE) whose rand() and a few "probe" places
; start with INT instructions; this TSR answers those interrupts
; (VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG) and the companion reads the ring buffer
; from DOSBox's memory. VEC_CHAR adds THAC0, the saving throws and thief skills to the
; game's inventory screen.
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
VEC_TEXT equ 0x63     ; PROBE_TEXT
VEC_MSG  equ 0x64     ; PROBE_MSG
VEC_CHAR equ 0x65     ; PROBE_CHAR
VEC_TURN equ 0xF1     ; PROBE_TURN (not 66h-6Fh: the game calls those, looking for drivers)
VEC_USE  equ 0xF2     ; PROBE_USE
VEC_VIEW equ 0xF3     ; PROBE_VIEW
TSIZE    equ 8192     ; bytes in the text buffer

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
sig      db 'DSCLOGv7'          ; +0
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
vectors  db VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG  ; +112 the interrupts the patched game uses
hooked   db 0                   ; +117 1 once the vectors are ours
int_rand_off dw int_rand        ; +118 offset of INT_RAND (VEC_RAND's handler) in this segment
gpl_hook_off dw gpl_hook        ; +120 offset of GPL_HOOK in this segment
gpl_chain dd 0                  ; +122 the game's own hook, which GPL_HOOK passes on to
tpos     dw 0                   ; +126 bytes written to the text buffer so far (wraps at 65536)
tbuf_off dw tbuf                ; +128 offset of the text buffer in this segment
tsize    dw TSIZE               ; +130 its size (a power of two)
probe_text_off dw probe_text    ; +132 offset of PROBE_TEXT in this segment
probe_msg_off dw probe_msg      ; +134 offset of PROBE_MSG in this segment
probe_char_off dw probe_char    ; +136 offset of PROBE_CHAR in this segment
turn_seq  dw 0                  ; +138 turns that have ended in a fight (PROBE_TURN counts them)
reply_seq dw 0                  ; +140 the companion sets this to TURN_SEQ once MSG_BUF is ready
popups_on dw 0                  ; +142 the companion sets 1 to have turn summaries shown
msg_off   dw msg_buf            ; +144 offset of MSG_BUF: the summary, NUL-terminated
ended     dw 0                  ; +146 the combatant whose turn just ended
slots_off dw slots_text         ; +148 offset of SLOTS_TEXT: 4 x SLOTS_SIZE bytes, one per party
                                ;      member, lines separated by "|", NUL-terminated (the companion
                                ;      keeps them up to date); PROBE_USE draws them

; TEXT BUFFER: what the game sends to its dialogue window, as records of
;   byte 0FEh, byte kind (the dialogue window's: 0 = a reply to choose, the
;   first of a list being its title; 1 = a portrait; 2 = text; 3 = show the
;   replies; 4 = clear. 16 = a message box),
;   dword first argument (the text's far pointer, for 0, 2 and 16), word second
;   argument, word length, then that many bytes of text (for kinds 0, 2 and 16).
; A record is complete once TPOS counts it.

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

; GPL_HOOK: the game's script interpreter calls the far pointer at DS:00ACh with
; each command's number before running it. The companion points it here and
; puts the game's own hook in GPL_CHAIN. Records the command (kind 3), then
; passes on to the game's hook.
gpl_hook:
        push si
        mov si, sp
        sub si, 4               ; SS:SI+6 = our return address
        push ax
        mov ax, [ss:si+10]      ; the command number
        mov word [cs:kind], 3
        call record
        pop ax
        pop si
        jmp far [cs:gpl_chain]

; PROBE_TEXT: INT VEC_TEXT replaces "push bp / mov bp,sp" (3 bytes: INT + NOP) at
; the start of the game's routine that feeds its dialogue window
; (kind, dword, word). Copies what it's given to the text buffer, then does the
; replaced instructions for the routine.
probe_text:
        call text_enter         ; SS:BP+16 = the routine's arguments
        mov cl, [bp+16]
        lds si, [bp+18]
        mov dx, [bp+22]
        jmp text_leave

; PROBE_MSG: the same for the game's message box routine (far pointer to the
; message), recorded as kind 16.
probe_msg:
        call text_enter
        mov cl, 16
        lds si, [bp+16]
        xor dx, dx
        jmp text_leave

text_enter:                     ; take the interrupt frame off, save registers, BP = SP
        pop word [cs:t_ret]
        pop word [cs:t_ip]      ; the routine's stack is underneath the interrupt frame
        pop word [cs:t_cs]
        pop word [cs:t_fl]
        sti
        push ax
        push bx
        push cx
        push dx
        push si
        push ds
        push bp
        mov bp, sp              ; SS:BP+14 = return address of the routine, +18 its arguments
        add bp, 2               ; ... so that +16 is the first argument
        jmp [cs:t_ret]

text_leave:                     ; record CL = kind, DS:SI = dword, DX = word, then return
        mov bx, [cs:tpos]
        mov al, 0xFE
        call tput
        mov al, cl
        call tput
        mov ax, si
        call tputw
        mov ax, ds
        call tputw
        mov ax, dx
        call tputw
        xor ax, ax
        cmp cl, 0
        je .text
        cmp cl, 2
        je .text
        cmp cl, 16
        jne .len                ; the other kinds have no text (and no pointer)
.text:
        mov ax, ds
        or ax, si
        jz .len
        push si
        xor ax, ax
.count:
        cmp byte [si], 0
        je .counted
        inc si
        inc ax
        cmp ax, 400
        jb .count
.counted:
        pop si
.len:
        mov cx, ax
        call tputw
        jcxz .done
.copy:
        lodsb
        call tput
        loop .copy
.done:
        mov [cs:tpos], bx       ; publish the record
        pop bp
        pop ds
        pop si
        pop dx
        pop cx
        pop bx
        pop ax
        push bp                 ; the replaced instructions
        mov bp, sp
        push word [cs:t_fl]
        push word [cs:t_cs]
        push word [cs:t_ip]
        iret

; PROBE_INV: INT VEC_CHAR replaces "add sp,0Eh" (3 bytes: INT + NOP) in the inventory
; screen's routine for its right-hand panel, straight after the weapon lines (AX = how many
; lines they took). Does the add, then adds in the game's own lettering: THAC0 and the five
; saving throws above STR, and for a thief the eight skills in a column right of the
; abilities (below the weapons, three of which reach the buttons, there'd be no room).
; The routine's code holds the (relocated) far address of the game's text routine at a
; fixed distance before the patch: it is read from there.
IV_PATCH  equ 0x6F6BF           ; DSUN.EXE offsets
IV_DRAW   equ 0x6F626           ; "lcall 0150h:016Dh" operand: the text routine
IV_WHO    equ 0x6F634           ; "mov ax,0348h" operand: segment of the character number (+25Bh)
THIEF_CLASS equ 17
THIEF_TABLE equ 0x3FAA - 0x4356 ; the thief tables' segment, relative to DS
probe_char:
        pop word [cs:t_ip]
        pop word [cs:t_cs]
        pop word [cs:t_fl]
        add sp, 0x0E            ; the replaced instruction
        sti
        pushad
        push es
        push fs
        push gs
        mov es, [cs:t_cs]
        mov di, [cs:t_ip]
        sub di, 2               ; ES:DI = the patch
        mov eax, [es:di + IV_DRAW - IV_PATCH]
        mov [cs:c_draw], eax
        mov fs, [es:di + IV_WHO - IV_PATCH]
        mov eax, [0x11A4]       ; the panel's window
        mov [cs:c_winptr], eax
        mov bx, [fs:0x25B]      ; the character on show
        imul ax, bx, 0x47
        les si, [0x1661]
        add si, ax              ; ES:SI = the character sheet
        cmp word [es:si + 0x10], 0
        je .done                ; an empty slot
        imul bx, bx, 0x3A
        lfs di, [0x1665]
        add di, bx              ; FS:DI = the creature record
        ; THAC0 and the saves
        mov al, [fs:di + 0x1F]
        mov bx, c_cells_top
        call c_cells_saves
        ; thief skills, for a character with thief levels
        xor cx, cx
        mov bx, 0x21
.cls:   cmp byte [es:si + bx], THIEF_CLASS
        je .thief
        inc bx
        inc cx
        cmp cx, 3
        jb .cls
        jmp .done
.thief: mov al, [es:si + bx + 3]  ; the thief level (levels follow the classes)
        call c_thief
.done:
        pop gs
        pop fs
        pop es
        popad
        push word [cs:t_fl]
        push word [cs:t_cs]
        push word [cs:t_ip]
        iret

; PROBE_VIEW: INT VEC_VIEW replaces "push dword 000B0140h" (6 bytes: INT + 4 NOPs) near the
; end of the View Character screen's routine for its upper panel, once the game has drawn
; its own lines. Adds THAC0 and the saves under the item icons, then does the push.
; The routine's code holds, at fixed distances before the patch, the (relocated) far address
; of the text routine, the segment of the panel's window handle and the segment of the
; selected character's number: they are read from there.
CH_PATCH  equ 0x8A471           ; DSUN.EXE offsets
CH_DRAW   equ 0x8A2C8           ; "lcall 0150h:016Dh" operand: the text routine
CH_WIN    equ 0x8A2BD           ; "mov ax,0430h" operand: segment of the window's far pointer
CH_WHO    equ 0x8A2D6           ; "mov ax,0348h" operand: segment of the character number (+25Bh)
probe_view:
        pop word [cs:t_ip]
        pop word [cs:t_cs]
        pop word [cs:t_fl]
        sti
        pushad
        push es
        push fs
        mov es, [cs:t_cs]
        mov di, [cs:t_ip]
        sub di, 2               ; ES:DI = the patch
        mov eax, [es:di + CH_DRAW - CH_PATCH]
        mov [cs:c_draw], eax
        mov fs, [es:di + CH_WIN - CH_PATCH]
        mov eax, [fs:0]         ; the panel's window
        mov [cs:c_winptr], eax
        mov fs, [es:di + CH_WHO - CH_PATCH]
        mov bx, [fs:0x25B]      ; the character on show
        cmp bx, 3
        ja .done
        imul ax, bx, 0x47
        les si, [0x1661]
        add si, ax              ; ES:SI = the character sheet
        cmp word [es:si + 0x10], 0
        je .done                ; an empty slot
        imul bx, bx, 0x3A
        lfs di, [0x1665]
        mov al, [fs:di + bx + 0x1F]  ; THAC0
        mov di, v_thac0 + 7
        call c_itoa
        mov di, v_saves1 + 5
        mov al, [es:si + 0x37]
        call v_two
        mov al, [es:si + 0x38]
        call v_two
        mov al, [es:si + 0x39]
        call v_two
        mov di, v_saves2 + 5
        mov al, [es:si + 0x3A]
        call v_two
        mov al, [es:si + 0x3B]
        call v_two
        push word 0x3A          ; under the item icons
        push word 0xCD
        push cs
        push word v_thac0
        call c_draw_line
        push word 0x41
        push word 0xCD
        push cs
        push word v_saves1
        call c_draw_line
        push word 0x48
        push word 0xCD
        push cs
        push word v_saves2
        call c_draw_line
.done:  pop fs
        pop es
        popad
        push dword 0x000B0140   ; the replaced instruction
        push word [cs:t_fl]
        push word [cs:t_cs]
        push word [cs:t_ip]
        iret

v_two:                          ; AL (0-99) -> two digits (a space for a leading 0) and a space
        push bx                 ; at CS:DI; DI moves on
        xor ah, ah
        mov bl, 10
        div bl
        add ax, '00'
        cmp al, '0'
        jne .tens
        mov al, ' '
.tens:  mov [cs:di], al
        mov [cs:di + 1], ah
        mov byte [cs:di + 2], ' '
        add di, 3
        pop bx
        ret

v_thac0  db 'THAC0: ', 0, 0, 0, 0
v_saves1 db 'SAVE:00 00 00 ', 0
v_saves2 db '     00 00 ', 0

; THAC0 (AL) and the saves (sheet +37h..+3Bh at ES:SI), as the cells at CS:BX say
c_cells_saves:
        mov [cs:c_vals], al
        mov eax, [es:si + 0x37]
        mov [cs:c_vals + 1], eax
        mov al, [es:si + 0x3B]
        mov [cs:c_vals + 5], al
        mov cx, 6
        jmp c_cells

; the eight thief skills of the character (sheet ES:SI, creature FS:DI, thief level AL):
; base + 4 a level + the race's adjustment + DEX, from the game's tables (before armour,
; as the Templar's Ledger shows them)
c_thief:
        push si
        mov dl, al
        shl dl, 2               ; 4 a level
        mov ax, ds
        add ax, THIEF_TABLE
        mov gs, ax
        mov dh, [fs:di + 0x23]  ; DEX
        movzx di, byte [es:si + 0x18]  ; race
        shl di, 3
        add di, 8               ; +8 + race * 8
        xor bx, bx
.skill: movsx ax, byte [gs:bx]  ; base
        movzx cx, dl
        add ax, cx
        movsx cx, byte [gs:bx + di]  ; race
        add ax, cx
        push dx                 ; DEX: -5 a point below LOW, +5 a point above HIGH, -3 above TOP
        movzx dx, dh
        movzx cx, byte [gs:bx + 0x90]
        sub cx, dx
        jle .nolow
        imul cx, cx, 5
        sub ax, cx
.nolow: mov cx, dx
        push dx
        movzx dx, byte [gs:bx + 0x98]
        sub cx, dx
        pop dx
        jle .nohigh
        imul cx, cx, 5
        add ax, cx
.nohigh:
        mov cx, dx
        push dx
        movzx dx, byte [gs:bx + 0xA0]
        sub cx, dx
        pop dx
        jle .notop
        imul cx, cx, 3
        sub ax, cx
.notop: pop dx
        cmp ax, 0
        jge .pos
        xor ax, ax              ; below 0: shown as 0
.pos:   cmp ax, 255
        jbe .fits
        mov ax, 255
.fits:  mov [cs:c_vals + bx], al
        inc bx
        cmp bx, 8
        jb .skill
        pop si
        mov al, [cs:c_vals + 5] ; only the five the game ever rolls: move silently, hide in
        mov [cs:c_vals + 3], al ; shadows and read languages are never checked (the Templar's
        mov al, [cs:c_vals + 6] ; Ledger's script decoder found no script asking for them)
        mov [cs:c_vals + 4], al
        mov bx, c_cells_thief
        mov cx, 5
        ; fall through

; CX cells at CS:BX: each x, y, label offset, value's x (words); the values are C_VALS in
; order. Keeps ES, SI, DI.
c_cells:
        push es
        push si
        push di
        xor si, si
.cell:  push cx
        push bx
        push word [cs:bx + 2]   ; y
        push word [cs:bx]       ; x
        push cs
        push word [cs:bx + 4]   ; the label
        call c_draw_line
        pop bx
        push bx
        mov al, [cs:c_vals + si]
        mov di, c_num
        call c_itoa
        push word [cs:bx + 2]
        push word [cs:bx + 6]   ; the value's x
        push cs
        push word c_num
        call c_draw_line
        pop bx
        pop cx
        add bx, 8
        inc si
        loop .cell
        pop di
        pop si
        pop es
        ret

c_draw_line:                    ; stack: text far pointer, x, y (near return address first)
        push bp
        mov bp, sp
        push dword [bp + 4]     ; the text, for the format's %s
        push word [0x3270]      ; the colours, as the game sets them for its AC line
        push word 0x14
        push word [0x326E]
        push dword 0x00FE00FF
        push word 0
        push ds
        push word 0x0E11        ; the format: "%C%C%C%s"
        push dword [bp + 8]     ; x, y
        push dword [cs:c_winptr]  ; the window
        call far [cs:c_draw]
        add sp, 0x1C
        pop bp
        ret 8

c_itoa:                         ; AL (unsigned) -> decimal at CS:DI, NUL-terminated; keeps BX, CX
        push bx
        push cx
        xor ah, ah
        mov bl, 10
        xor cx, cx
.div:   div bl
        push ax                 ; AH = a digit
        inc cx
        xor ah, ah
        or al, al
        jnz .div
.put:   pop ax
        add ah, '0'
        mov [cs:di], ah
        inc di
        loop .put
        mov byte [cs:di], 0
        pop cx
        pop bx
        ret

; cells: x, y, label, value's x (window coordinates: the stats' labels are at x 0ECh, their
; values at 104h, STR at y 35h, lines 7 apart)
c_cells_top:
        dw 0xEC, 0x10, l_thac0, 0x111
        dw 0xEC, 0x17, l_ppd, 0x103,  0x113, 0x17, l_rsw, 0x12A
        dw 0xEC, 0x1E, l_pp, 0x103,   0x113, 0x1E, l_bw, 0x12A
        dw 0xEC, 0x25, l_sp, 0x103
c_cells_thief:                  ; right of the abilities (whose values end by 10Eh), in the
        dw 0x113, 0x27, l_pick, 0x12D  ; saves' second column: from beside SP down,
        dw 0x113, 0x2E, l_lock, 0x12D  ; level with STR..CON
        dw 0x113, 0x35, l_trap, 0x12D
        dw 0x113, 0x3C, l_hear, 0x12D
        dw 0x113, 0x43, l_clmb, 0x12D
l_thac0 db 'THAC0:', 0
l_ppd   db 'PPD', 0
l_rsw   db 'RSW', 0
l_pp    db 'PP', 0
l_bw    db 'BW', 0
l_sp    db 'SP', 0
l_pick  db 'PICK', 0
l_lock  db 'LOCK', 0
l_trap  db 'TRAP', 0
l_hear  db 'HEAR', 0
l_clmb  db 'CLMB', 0
c_vals  times 8 db 0
c_num   db 0, 0, 0, 0
c_draw  dd 0
c_winptr dd 0


; PROBE_TURN: INT VEC_TURN replaces "add sp,4" (3 bytes: INT + NOP) in the game's combat
; loop, straight after the call that runs combat and may pass the turn on (it is given the
; address of DS:4979h, whose turn it is). When the turn has changed and the companion wants
; summaries, note whose turn ended, wait a moment (at most TURN_WAIT timer ticks) for the
; companion to put that turn's summary in MSG_BUF, and show it with the game's own message
; window, as the game's scripts do for a narration: the emblem instead of a portrait, the
; text, then "Continue" to click (the scripts' own "Press continue"), then CLOSE.
; The dialogue window's routines are reached through the game's overlay stub for them,
; whose segment is a fixed distance from the game's data segment.
DLG_STUB  equ 0x42CA - 0x4356   ; the stub's segment (DSUN.EXE: 42CAh) less the data segment's
DLG_FEED  equ 0x25              ; the window's input: (kind, far text, word), see the text buffer
DLG_WAIT  equ 0x34              ; wait for a reply to be clicked
S_PRESS   equ 0x15E8            ; DS: "Press continue"
S_CONT    equ 0x15F7            ; DS: "Continue"
S_CLOSE   equ 0x1F11            ; DS: "CLOSE"
TURN_WAIT equ 7                 ; timer ticks (55 ms each)
probe_turn:                     ; (re-entered while the window waits: all state on the stack)
        push bp                 ; the replaced "add sp,4": move the interrupt frame (and BP)
        mov bp, sp              ; up over the 4 bytes, so IRET returns with them gone
        push ax
        mov ax, [bp + 6]
        mov [bp + 10], ax       ; flags
        mov ax, [bp + 4]
        mov [bp + 8], ax        ; CS
        mov ax, [bp + 2]
        mov [bp + 6], ax        ; IP
        mov ax, [bp]
        mov [bp + 4], ax        ; BP
        pop ax
        mov sp, bp
        add sp, 4
        pop bp
        sti
        pushad
        push es
        cmp byte [cs:showing], 0
        jne .out                ; a summary is up: leave the game's loop alone meanwhile
        mov bx, [0x4979]        ; whose turn it is now
        xchg bx, [cs:last_turn]
        cmp bx, [cs:last_turn]
        je .out                 ; the same as last time
        cmp word [cs:popups_on], 0
        je .out
        mov [cs:ended], bx
        inc word [cs:turn_seq]
        xor ax, ax
        mov es, ax
        mov dx, [es:0x46C]      ; the BIOS timer
.wait:  mov ax, [cs:reply_seq]
        cmp ax, [cs:turn_seq]
        je .ready
        mov ax, [es:0x46C]
        sub ax, dx
        cmp ax, TURN_WAIT
        jb .wait
        jmp .out                ; no answer: the companion isn't reading
.ready: cmp byte [cs:msg_buf], 0
        je .out                 ; nothing to say about that turn
        mov byte [cs:showing], 1
        mov ax, ds
        add ax, DLG_STUB
        mov [cs:dlg + 2], ax
        mov word [cs:dlg], DLG_FEED
        xor bx, bx
        push word 0             ; the emblem (portrait 0)
        push bx
        push bx
        push word 1
        call far [cs:dlg]
        add sp, 8
        push word 0             ; the summary
        push cs
        push word msg_buf
        push word 2
        call far [cs:dlg]
        add sp, 8
        push word 0             ; "Press continue": the replies' title, then the one reply
        push ds
        push word S_PRESS
        push word 0
        call far [cs:dlg]
        add sp, 8
        push word 0
        push ds
        push word S_CONT
        push word 0
        call far [cs:dlg]
        add sp, 8
        push word 0             ; show the reply
        push dword 0
        push word 3
        call far [cs:dlg]
        add sp, 8
        mov word [cs:dlg], DLG_WAIT
        call far [cs:dlg]       ; until it's clicked
        mov word [cs:dlg], DLG_FEED
        push word 0             ; and close the window
        push ds
        push word S_CLOSE
        push word 2
        call far [cs:dlg]
        add sp, 8
        mov byte [cs:showing], 0
.out:   pop es
        popad
        iret

dlg     dd 0                    ; the dialogue window routine being called
showing db 0                    ; 1 while PROBE_TURN has a summary up
last_turn dw 0xFFFF

; PROBE_USE: INT VEC_USE replaces "add sp,0Ch" (3 bytes: INT + NOP) in the USE (cast spells)
; screen's routine that labels its LEVEL button, which runs whenever the screen is drawn
; or the level changes. Draws the selected character's spell slots (SLOTS_TEXT, from the
; companion) in the empty panel under the spells, with the game's own text routine.
USE_TEXT_SEG equ 0x2B7A - 0x4356 ; the text routine's segment (DSUN.EXE: 2B7Ah) less DS's
USE_TEXT_OFF equ 0x16D
USE_WHO_SEG  equ 0x3931 - 0x4356 ; the selected character's number is at this segment:25Bh
SLOTS_SIZE   equ 96
MSG_SIZE     equ 900         ; the turn summary: the dialogue window keeps up to 1024 bytes
probe_use:
        push bp                 ; the replaced "add sp,0Ch": move the interrupt frame (and BP)
        mov bp, sp              ; up over the 12 bytes
        push ax
        mov ax, [bp + 6]
        mov [bp + 18], ax
        mov ax, [bp + 4]
        mov [bp + 16], ax
        mov ax, [bp + 2]
        mov [bp + 14], ax
        mov ax, [bp]
        mov [bp + 12], ax
        pop ax
        mov sp, bp
        add sp, 12
        pop bp
        sti
        pushad
        push es
        push fs
        mov ax, ds
        add ax, USE_WHO_SEG
        mov es, ax
        mov bx, [es:0x25B]      ; the character on show
        cmp bx, 3
        ja .done
        imul si, bx, SLOTS_SIZE
        add si, slots_text
        cmp byte [cs:si], 0
        je .done                ; no spells
        mov ax, ds
        add ax, USE_TEXT_SEG
        mov [cs:c_draw + 2], ax
        mov word [cs:c_draw], USE_TEXT_OFF
        mov eax, [0x11A4]       ; the screen's window
        mov [cs:c_winptr], eax
        mov dx, USE_FIRST_Y
.line:  mov di, u_line          ; copy one line (up to "|" or the end) and draw it
.copy:  mov al, [cs:si]
        cmp al, '|'
        je .cut
        cmp al, 0
        je .cut
        mov [cs:di], al
        inc si
        inc di
        cmp di, u_line + SLOTS_SIZE - 1
        jb .copy
.cut:   mov byte [cs:di], 0
        push si
        push dx
        push dx                 ; y
        push word USE_X         ; x
        push cs
        push word u_line
        call c_draw_line
        pop dx
        pop si
        add dx, USE_STEP
        cmp byte [cs:si], '|'
        jne .done
        inc si
        cmp dx, USE_LAST_Y
        jbe .line
.done:  pop fs
        pop es
        popad
        iret
USE_X      equ 0x96             ; the panel under the spells (window coordinates): its top,
USE_FIRST_Y equ 0x6C            ; three lines above where the icons of usable items (fruit,
USE_STEP   equ 7                ; wands...) go, along the panel's bottom from 0x81
USE_LAST_Y equ 0x7A
u_line  times SLOTS_SIZE db 0
slots_text times 4 * SLOTS_SIZE db 0
msg_buf times MSG_SIZE db 0

tput:                           ; AL -> text buffer at position BX
        push bx
        and bx, TSIZE - 1
        mov [cs:tbuf+bx], al
        pop bx
        inc bx
        ret

tputw:
        call tput
        mov al, ah
        jmp tput

t_ret   dw 0
t_ip    dw 0
t_cs    dw 0
t_fl    dw 0
kind    dw 0
extra   dw 0
SPELL_SEG equ 2 + 0x79BB7 - 0x79A85  ; return address - (DSUN.EXE offsets: patch, mov ax's operand)

align 16
ring:   times NENT*ESIZE db 0
tbuf:   times TSIZE db 0
resident_end:

install:                        ; DS = ES = PSP, CS = the image
        mov [cs:psp], es
        push cs
        pop ds
        mov si, all_vectors     ; the vectors must be free
        mov cx, 9
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
        mov ax, 2500h + VEC_TEXT
        mov dx, probe_text
        int 21h
        mov ax, 2500h + VEC_MSG
        mov dx, probe_msg
        int 21h
        mov ax, 2500h + VEC_CHAR
        mov dx, probe_char
        int 21h
        mov ax, 2500h + VEC_TURN
        mov dx, probe_turn
        int 21h
        mov ax, 2500h + VEC_USE
        mov dx, probe_use
        int 21h
        mov ax, 2500h + VEC_VIEW
        mov dx, probe_view
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
busy    db 'DSCLOG: interrupts 60h-65h or F1h-F3h are in use (already loaded?). Not loaded.', 13, 10, '$'
all_vectors db VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG, VEC_CHAR, VEC_TURN, VEC_USE, VEC_VIEW

        align 16, db 0
image_len equ $ - $$
file_len  equ image_len + 32
