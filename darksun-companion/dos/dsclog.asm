; DSCLOG.EXE - dice log helper for the Dark Sun companion.
;
; A tiny TSR that stays resident (load it high with LH) and holds a ring
; buffer plus a replacement for the game's Borland rand(). The companion runs a
; patched copy of the game (DSUNLOG.EXE) whose rand() and a few "probe" places
; start with INT instructions; this TSR answers those interrupts
; (VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG) and the companion reads the ring buffer
; from DOSBox's memory. VEC_CHAR adds THAC0, the saving throws and thief skills to the
; game's inventory screen. VEC_RING_AC and VEC_RING_SAVE make a ring with a plus (the
; companion's Ring +1) better the AC and saving throws of whoever wears it.
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
VEC_WIN  equ 0xF4     ; PROBE_WIN
VEC_LOOK equ 0xF5     ; PROBE_LOOK
VEC_UNLOOK equ 0xF6   ; PROBE_UNLOOK
VEC_NEXT equ 0xF7     ; PROBE_NEXT
VEC_RING_AC equ 0xF8  ; PROBE_RING_AC
VEC_RING_SAVE equ 0xF9  ; PROBE_RING_SAVE
VEC_WEAPON equ 0xFA   ; PROBE_WEAPON
VEC_MOVE   equ 0xFB   ; PROBE_MOVE
VEC_PICK   equ 0xFC   ; PROBE_PICK
VEC_USE_ITEM equ 0xFD ; PROBE_USE_ITEM
VEC_TWO    equ 0xFE   ; PROBE_TWO
VEC_DOUBLE equ 0xF0   ; PROBE_DOUBLE
VEC_GRACE_CAST equ 0xED    ; PROBE_GRACE_CAST
VEC_GRACE_EFFECT equ 0xEE  ; PROBE_GRACE_EFFECT
VEC_GRACE_ABILITY equ 0xEF ; PROBE_GRACE_ABILITY
VEC_NAMES_SIZE equ 0xEC    ; PROBE_NAMES_SIZE
VEC_NAMES_FILL equ 0xEB    ; PROBE_NAMES_FILL
VEC_STEALTH equ 0xEA       ; PROBE_STEALTH
VEC_TYPES_SIZE equ 0xE9    ; PROBE_TYPES_SIZE
VEC_TYPES_FILL equ 0xE8    ; PROBE_TYPES_FILL
VEC_LEVEL equ 0xE7         ; PROBE_LEVEL
VEC_HD_ROLL equ 0xE6       ; PROBE_HD_ROLL
VEC_HD_CON equ 0xE5        ; PROBE_HD_CON
VEC_THIEF_SKILL equ 0xE4   ; PROBE_THIEF_SKILL
VEC_TWO_HANDED equ 0xE3    ; PROBE_TWO_HANDED
VEC_SPELL_TEXT equ 0xE2    ; PROBE_SPELL_TEXT
VEC_CHUNK_ID equ 0xE1      ; PROBE_CHUNK_ID
VEC_FLOOR_ALL equ 0xE0     ; PROBE_FLOOR (the whole view's floor)
VEC_FLOOR_RECT equ 0xDF    ; PROBE_FLOOR (a rectangle's floor)
VEC_REDRAW equ 0xDE        ; PROBE_REDRAW
VEC_REDRAW_ALL equ 0xDD    ; PROBE_REDRAW_ALL
VEC_SCROLL equ 0xDC        ; PROBE_SCROLL
VEC_HIT    equ 0xDB        ; PROBE_HIT
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
sig      db 'DSCLOGvU'          ; +0
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
look_seq   dw 0                 ; +150 monsters looked at in a fight (PROBE_LOOK counts them)
look_reply dw 0                 ; +152 the companion sets this to LOOK_SEQ once LOOK_TEXT is ready
look_who   dw 0                 ; +154 the combatant looked at
look_off   dw look_text         ; +156 offset of LOOK_TEXT: up to 3 short lines for the Look box,
                                ;      separated by "|", NUL-terminated
look_full_off dw look_full      ; +158 offset of LOOK_FULL: the whole description, shown in the
                                ;      dialogue window afterwards (empty: none)
look_on    dw 0                 ; +160 the companion sets 1 to have monsters described
stats_off  dw stats             ; +162 offset of STATS: for each party member, the THAC0 and
                                ;      saves as they stand now (see STATS)
stats_stamp dw 0                ; +164 the BIOS timer when the companion last wrote STATS: older
                                ;      than STATS_FRESH, the screens show the game's own numbers
stats_req  dw 0                 ; +166 counted up when a screen is about to show STATS ...
stats_reply dw 0                ; +168 ... and set to it by the companion once STATS are up to date
rules      dw 0                 ; +170 rule changes the companion turns on (RULE_HELMS, RULE_BOOTS)
pick_seq   dw 0                 ; +172 P pressed in a conversation (PROBE_PICK counts them) ...
pick_reply dw 0                 ; +174 ... and set to it by the companion once PICK_TEXT is ready
pick_off   dw pick_text         ; +176 offset of PICK_TEXT: what came of it, NUL-terminated (empty:
                                ;      nothing to show)
pick_on    dw 0                 ; +178 the companion sets 1 to take P as picking a pocket
use_seq    dw 0                 ; +180 an item used on something on the map (PROBE_USE_ITEM counts) ...
use_reply  dw 0                 ; +182 ... and set to it by the companion once it has had its say
use_who    dw 0                 ; +184 the object it was used on
use_taken  dw 0                 ; +186 the companion sets 1 when it was one of its own (the thieving
                                ;      tools): the game then does nothing more, and PICK_TEXT is shown;
                                ;      2 when it is used up as well (the cooked vulture, eaten)
use_item   dw 0                 ; +188 the item used (FFFFh: none)
swap_on    dw 0                 ; +190 the companion sets 1 to have the next dialogue text that
                                ;      starts with SWAP_MATCH shown as SWAP_TEXT instead (once)
swap_seq   dw 0                 ; +192 counted up when it has been
swap_off   dw swap_match        ; +194 offset of SWAP_MATCH (SWAP_SIZE bytes, NUL-terminated),
                                ;      then SWAP_TEXT (TSIZE_SWAP bytes)
names_off  dw extra_names       ; +196 offset of EXTRA_NAMES: the names past the game's own (NAMES_EXTRA
                                ;      of NAME_SIZE bytes), copied into the game's table each time it loads
names_count dw NAMES_EXTRA      ; +198 how many
names_ptr  dd 0                 ; +200 the game's name table, as last loaded with them (0: not yet)
stealth    dw 0                 ; +204 the companion sets bit N when party member N is hidden and
                                ;      unheard (RULE_STEALTH): their next attack is from behind
stealth_used dw 0               ; +206 counted up each time one is (the bit cleared)
types_off  dw extra_types       ; +208 offset of EXTRA_TYPES: item types past the game's own
                                ;      (TYPES_EXTRA of TYPE_SIZE bytes), copied in as it loads them
types_count dw TYPES_EXTRA      ; +210 how many
types_first dw 0                ; +212 the number the first of them gets (the game's own count)
types_ptr  dd 0                 ; +214 the game's item type table, as last loaded with them
objects_on dw 0                 ; +218 1 once the game has opened the companion's copy of
                                ;      SEGOBJEX.GFF (its icons: see PROBE_DOS_OPEN)
shadows_on dw 0                 ; +220 the companion sets 1 to have figures cast shadows (SHADOWS)
shadow_tab_off dw shadow_tab    ; +222 offset of SHADOW_TAB: a byte for each of the game's 520 things,
                                ;      1 for those that cast a shadow (the companion keeps it)
dark_build dw 0                 ; +224 the companion sets 1 to have DARK made again from the palette
                                ;      (after the area, so the palette, changes); 0 once it is
shadow_passes dw 0              ; +226 shadow passes drawn (counted)
scroll_on  dw 0                 ; +228 the companion sets SCROLL_MIDDLE and/or SCROLL_RIGHT to have
                                ;      a drag with that button scroll the map (SCROLLING)
pan_x      dw 0                 ; +230 the companion adds to these (wrapping) to scroll the map by
pan_y      dw 0                 ; +232   as many pixels (the mouse wheel, read in Windows)
dust_on    dw 0                 ; +234 the companion sets 1 once LIGHT is made, to have walkers raise
                                ;      dust (DUST)
light_off  dw light             ; +236 offset of LIGHT: each colour's lighter one (0: none, not ground
                                ;      dust shows on), the companion makes it from DAC
dac_off    dw dac               ; +238 offset of DAC: the palette as DARK was last made from it
dust_puffs dw 0                 ; +240 puffs of dust raised (counted)
view_redraw dw 0                ; +242 the companion sets 1 to have the view drawn again (all of it, from
                                ;      the main loop: VIEW_AGAIN), as it is once it has been
rings_on   dw 0                 ; +244 the companion sets 1 to have rings drawn under the things RING_TAB
                                ;      marks (RINGS), once RED is made
ring_tab_off dw ring_tab        ; +246 offset of RING_TAB: a byte for each of the game's 520 things: 1 a
                                ;      ring, 2 the chosen one's (brighter, thicker)
red_off    dw red               ; +248 offset of RED: each colour's reddened one (0: none), as LIGHT
target_on  dw 0                 ; +250 the companion sets 1 while Tab chooses an enemy (TARGETING)
tab_seq    dw 0                 ; +252 Tab pressed (counted) ...
back_seq   dw 0                 ; +254 ... and Shift+Tab
hit_target dw 0xFFFF            ; +256 the enemy chosen (the companion sets it; FFFFh: none)
attack_seq dw 0                 ; +258 Enter pressed on it (counted)
main_ticks dw 0                 ; +260 the map's main loop run (counted: not while a talk, menu or
                                ;      shop is open)

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
        cmp word [cs:swap_on], 0
        je .record
        cmp byte [bp+16], 2     ; text for the window
        jne .record
        lds si, [bp+18]
        mov ax, ds
        or ax, si
        jz .record
        mov bx, swap_match
.same:  mov al, [cs:bx]
        or al, al
        jz .swap                ; all of SWAP_MATCH matched
        cmp al, [si]
        jne .record
        inc si
        inc bx
        jmp .same
.swap:  mov word [bp+18], swap_text  ; the routine is given ours instead
        mov [bp+20], cs
        mov word [cs:swap_on], 0
        inc word [cs:swap_seq]
.record:
        mov cl, [bp+16]
        lds si, [bp+18]
        mov dx, [bp+22]
        jmp text_leave

SWAP_SIZE equ 64
swap_match times SWAP_SIZE db 0
swap_text  times 240 db 0

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
        mov [cs:c_who], bx
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
        ; the DEX reaction adjustment (the game's table for initiative holds the same numbers),
        ; worked out now, so a change of DEX shows the next time the panel is drawn
        mov byte [cs:c_react], NO_REACT
        movzx bx, byte [fs:di + 0x23]
        cmp bx, 26
        jae .thieves
        mov al, [bx + DEX_REACTION]
        mov [cs:c_react], al
        mov al, [bx + DEX_DEFENCE]   ; and the defensive adjustment (on AC; on saves against
        mov [cs:c_defence], al       ; what can be dodged, the other way round)
.thieves:
        ; thief skills, for a character with thief levels
        xor cx, cx
        mov bx, 0x21
.cls:   cmp byte [es:si + bx], THIEF_CLASS
        je .thief
        inc bx
        inc cx
        cmp cx, 3
        jb .cls
        ; no thief levels: a ranger's move silently and hide in shadows (the companion's
        ; stealth rule), in the thief's places, when the companion sends them
        mov bx, [cs:c_who]
        call stats_for
        jc .react
        cmp byte [cs:bx + 17], STATS_RANGER
        jne .react
        mov ax, [cs:bx + 18 + 3]
        mov [cs:c_vals], ax
        mov bx, c_cells_thief + 3 * 8
        mov cx, 2
        mov byte [cs:c_signed], 0
        call c_cells
        jmp .react
.thief: mov al, [es:si + bx + 3]  ; the thief level (levels follow the classes)
        call c_thief
.react: mov al, [cs:c_react]      ; right of SP in the saves: "REAC +4"
        cmp al, NO_REACT
        je .done
        mov di, c_num
        test al, al
        jle .sign
        mov byte [cs:di], '+'
        inc di
.sign:  call c_itoa_s
        push word REACT_Y
        push word 0x113
        push cs
        push word l_react
        call c_draw_line
        push word REACT_Y
        push word REACT_VALUE_X
        push cs
        push word c_num
        call c_draw_line
        mov al, [cs:c_defence]    ; right of the AC line: "DEF -4"
        mov di, c_num
        test al, al
        jle .dsign
        mov byte [cs:di], '+'
        inc di
.dsign: call c_itoa_s
        push word DEF_Y
        push word 0x113
        push cs
        push word l_defence
        call c_draw_line
        push word DEF_Y
        push word DEF_VALUE_X
        push cs
        push word c_num
        call c_draw_line
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
        mov [cs:c_who], bx
        imul ax, bx, 0x47
        les si, [0x1661]
        add si, ax              ; ES:SI = the character sheet
        cmp word [es:si + 0x10], 0
        je .done                ; an empty slot
        imul bx, bx, 0x3A
        lfs di, [0x1665]
        mov al, [fs:di + bx + 0x1F]  ; THAC0
        call c_load_stats       ; (or the companion's, as they stand now)
        mov di, v_thac0 + 7
        mov al, [cs:c_vals]
        call c_itoa_s
        mov di, v_saves1 + 5
        mov al, [cs:c_vals + 1]
        call v_two
        mov al, [cs:c_vals + 2]
        call v_two
        mov al, [cs:c_vals + 3]
        call v_two
        mov di, v_saves2 + 5
        mov al, [cs:c_vals + 4]
        call v_two
        mov al, [cs:c_vals + 5]
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

; THAC0 (AL) and the saves (sheet +37h..+3Bh at ES:SI), or the companion's numbers as they
; stand now, as the cells at CS:BX say
c_cells_saves:
        call c_load_stats
        mov byte [cs:c_signed], 1  ; (THAC0 can be below 0)
        mov cx, 6
        jmp c_cells

; the eight thief skills of the character (sheet ES:SI, creature FS:DI, thief level AL):
; base + 4 a level + the race's adjustment + DEX, from the game's tables (before equipment and
; effects); the companion's numbers instead, which count those too, while it keeps STATS
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
        mov al, [cs:c_vals + 6] ; pick pockets, open locks, find traps, move silently and hide in
        mov [cs:c_vals + 5], al ; shadows (which the Templar's Ledger rolls: for picking pockets
                                ; and its stealth rule), and climb walls; not hear noise (one
                                ; script check in the game) or read languages (none)
        mov bx, [cs:c_who]      ; the companion's, with equipment and effects, if it keeps them
        call stats_for
        jc .ours
        cmp byte [cs:bx + 17], 0
        je .ours
        mov eax, [cs:bx + 18]
        mov [cs:c_vals], eax
        mov ax, [cs:bx + 22]
        mov [cs:c_vals + 4], ax
.ours:  mov bx, c_cells_thief
        mov cx, 6
        mov byte [cs:c_signed], 0
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
        or si, si
        jnz .unsigned
        cmp byte [cs:c_signed], 0
        je .unsigned
        call c_itoa_s           ; the first cell of THAC0 and the saves
        jmp .number
.unsigned:
        call c_itoa
.number:
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
        dw 0x113, 0x35, l_pick, 0x12D  ; saves' second column, level with STR..CHA
        dw 0x113, 0x3C, l_lock, 0x12D
        dw 0x113, 0x43, l_trap, 0x12D
        dw 0x113, 0x4A, l_move, 0x12D  ; (move silently)
        dw 0x113, 0x51, l_hide, 0x12D  ; (hide in shadows)
        dw 0x113, 0x58, l_clmb, 0x12D
l_thac0 db 'THAC0:', 0
l_ppd   db 'PPD', 0
l_rsw   db 'RSW', 0
l_pp    db 'PP', 0
l_bw    db 'BW', 0
l_sp    db 'SP', 0
l_pick  db 'PICK', 0
l_lock  db 'LOCK', 0
l_trap  db 'TRAP', 0
l_move  db 'MOVE', 0
l_hide  db 'HIDE', 0
l_clmb  db 'CLMB', 0
l_react db 'REAC', 0
l_defence db 'DEF', 0
c_react db 0
c_defence db 0
DEX_DEFENCE equ 0x07F6          ; DS: the DEX defensive adjustment (bytes, by score: on AC)
DEF_Y   equ 0x72                ; the AC line's y
DEF_VALUE_X equ 0x12D           ; (under the thief skills' values, as REAC's)
NO_REACT equ 0x80
DEX_REACTION equ 0x07DC         ; DS: the DEX reaction adjustment (bytes, by score)
REACT_Y equ 0x25                ; the saves' last row, right of SP (where BW and RSW are above)
REACT_VALUE_X equ 0x130         ; (a little right of the thief skills' values: REAC is the longer label)
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
        call turn_check
        pop es
        popad
        iret

; PROBE_NEXT: INT VEC_NEXT replaces "cmp word [bp-2],0" (4 bytes: INT + 2 NOPs, then the
; game's "jne +5") in the combat routine PROBE_TURN's call runs, once it has passed the turn on
; (DS:4979h) and before it plays the turn of a combatant the computer runs (a monster, or
; someone charmed). The game plays such a turn whole before its loop reaches PROBE_TURN, so
; without this the monster's rolls would join the summary of the turn before. Checks the turn
; as PROBE_TURN does, then goes on where the compare and the JNE would have gone.
; The combat routine is overlay code, and the summary's window is too: loading the window's
; code may move the combat routine or throw it out of memory while the window is up. The
; overlay manager then fixes up the return addresses it finds by following BP from frame to
; frame, so the way back is put in such a frame (as a far call's return address, with BP
; pointing at the game's), and taken from there afterwards: the combat routine where it is
; now, or the manager's trap that loads it again. (Returning to where it was before broke
; the game at random: the fight started over, or it stopped with "Stack overflow!")
probe_next:
        sti
        pushad
        push es
        mov bx, sp              ; the interrupt frame at BX+34: IP, CS, flags
        mov ax, [ss:bx + 34]    ; (the NOPs after the INT)
        add ax, 4               ; past the NOPs and the JNE when the compare finds 0 ...
        cmp word [bp - 2], 0    ; the replaced compare (BP: the combat routine's frame)
        je .frame
        add ax, 5               ; ... and to its target when not
.frame: push word [ss:bx + 36]
        push ax
        push bp
        mov bp, sp
        call turn_check
        pop bp
        pop ax                  ; the way back, as the overlay manager has left it
        pop dx
        mov bx, sp
        mov [ss:bx + 34], ax
        mov [ss:bx + 36], dx
        pop es
        popad
        iret

; PROBE_PICK: INT VEC_PICK replaces "jmp <ignore the key>" (3 bytes: INT + NOP) in the
; dialogue window's key handling, where a key that isn't one of the window's own (1-5, Y, N,
; the arrows...) goes, while the window waits for a reply. For P, when the companion wants it:
; count it, wait a moment for the companion to try the leader's hand at the pocket of the
; person talked to (PICK_TEXT, what came of it), and show that in the window, which goes on
; waiting for a reply as before. The window's code is overlay code: the way back is put in a
; frame the overlay manager can fix up, as for PROBE_NEXT.
PICK_JUMP equ 0x7DD70 - 0x7D9FF ; (DSUN.EXE) the JMP's target less the address after the INT
PICK_KEY  equ -0x0C             ; the key, at the key handler's BP-0Ch: scan code, character
PICK_WAIT equ 9                 ; timer ticks
probe_pick:
        sti
        pushad
        push es
        mov bx, sp              ; the interrupt frame at BX+34: IP, CS, flags
        add word [ss:bx + 34], PICK_JUMP  ; go on where the JMP went
        cmp word [cs:pick_on], 0
        je .out
        mov ax, [bp + PICK_KEY]
        and al, 0xDF            ; p or P
        cmp ax, 0x1950
        jne .out
        inc word [cs:pick_seq]
        xor ax, ax
        mov es, ax
        mov dx, [es:0x46C]      ; the BIOS timer
        call rtc_begin
.wait:  mov ax, [cs:pick_reply]
        cmp ax, [cs:pick_seq]
        je .ready
        mov ax, [es:0x46C]
        sub ax, dx
        cmp ax, PICK_WAIT
        jae .late_pick_reply
        call rtc_waited         ; (the BIOS clock can stand still: the game's timer
        jnc .wait               ;   doesn't always pass its ticks on; at most 2 s by the real-time clock)
.late_pick_reply:
        jmp .out                ; no answer: the companion isn't reading
.ready: cmp byte [cs:pick_text], 0
        je .out
        push word [ss:bx + 36]
        push word [ss:bx + 34]
        push bp
        mov bp, sp
        call pick_show
        pop bp
        pop ax
        pop dx
        mov bx, sp
        mov [ss:bx + 34], ax
        mov [ss:bx + 36], dx
.out:   pop es
        popad
        iret

; PICK_TEXT in the dialogue window, which is up and waiting for a reply: the text, then the
; replies shown again; DS = the game's
pick_show:
        mov ax, ds
        add ax, DLG_STUB
        mov [cs:dlg + 2], ax
        mov word [cs:dlg], DLG_FEED
        push word 0
        push cs
        push word pick_text
        push word 2
        call far [cs:dlg]
        add sp, 8
        push word 0
        push dword 0
        push word 3
        call far [cs:dlg]
        add sp, 8
        ret

PICK_SIZE equ 240
pick_text times PICK_SIZE db 0
drop_call dw DROP_OFF, 0
sound_call dw SOUND_OFF, 0

; PROBE_USE_ITEM: INT VEC_USE_ITEM replaces "cmp si,-1 / jne +3" (5 bytes: INT + 3 NOPs) in the
; routine that uses the item on the pointer on whatever is under it on the map (SI: that
; object, -1 for none). When the companion wants picked pockets: count it, wait a moment for
; the companion to see whether the item is its thieving tools and the object someone to rob
; (USE_TAKEN), and if so show what came of it (PICK_TEXT) and skip the game's own handling (the
; routine's end). Otherwise on as the compare and the JNE would have gone. Overlay code: the
; way back is put in a frame the overlay manager can fix up, as for PROBE_NEXT.
USE_NONE  equ 0x7361A - 0x73617 ; (DSUN.EXE) SI = -1: "jmp", less the address after the INT
USE_SOME  equ 0x7361D - 0x73617 ; the JNE's target
USE_DONE  equ 0x7371D - 0x73617 ; the routine's end
USE_HELD_SEG equ 0x73A15 - 0x73617 ; the routine's "mov dx,<segment>" for the pointer's items,
                                ;   whose operand the game fixes up when it loads the code
HELD      equ 0x17A0            ; DS: the pointer's item (in that segment at HELD * 10 + 44h)
HELD_LIST equ 0x179E            ; DS: the object whose item list is the pointer's
DGROUP_SEG equ 0x4356           ; the game's DS, less its load segment
DROP_SEG  equ 0x1A0A            ; and the resident routine (21134h in DSUN.EXE) that empties an
DROP_OFF  equ 0x1C94            ;   object's item list, putting the items back on the free list
SOUND_OFF equ 0x0663            ; the resident routine there that plays a sound (GPL's 5Dh)
QUEST_SOUND equ 53              ; the sound of a quest done (the game's scripts, with their XP)
probe_use_item:
        sti
        pushad
        push es
        mov bx, sp              ; the interrupt frame at BX+34: IP, CS, flags
        mov dx, USE_NONE
        cmp si, -1
        je .go
        mov dx, USE_SOME
        cmp word [cs:pick_on], 0
        je .go
        mov [cs:use_who], si
        mov word [cs:use_taken], 0
        mov word [cs:use_item], 0xFFFF
        mov di, [HELD]          ; (DS: the game's)
        cmp di, -1
        je .asked
        imul di, di, 10
        push ds
        push si
        lds si, [ss:bx + 34]    ; DS:SI: the code after the INT
        mov ds, [si + USE_HELD_SEG]  ; the pointer's items' segment, as fixed up
        mov ax, [di + 0x44]
        pop si
        pop ds
        mov [cs:use_item], ax
.asked:
        inc word [cs:use_seq]
        xor ax, ax
        mov es, ax
        mov cx, [es:0x46C]      ; the BIOS timer
        call rtc_begin
.wait:  mov ax, [cs:use_reply]
        cmp ax, [cs:use_seq]
        je .ready
        mov ax, [es:0x46C]
        sub ax, cx
        cmp ax, PICK_WAIT
        jae .late_use_reply
        call rtc_waited         ; (the BIOS clock can stand still: the game's timer
        jnc .wait               ;   doesn't always pass its ticks on; at most 2 s by the real-time clock)
.late_use_reply:
        jmp .go                 ; no answer: the companion isn't reading
.ready: cmp word [cs:use_taken], 0
        je .go
        cmp word [cs:use_taken], 2
        jne .kept
        ; 2: the item is used up (the cooked vulture, eaten): let go of the pointer's items the
        ; way the game does once it has counted coins picked up, and hold nothing
        push bx
        mov ax, ds
        sub ax, DGROUP_SEG - DROP_SEG
        mov [cs:drop_call + 2], ax
        push word [HELD_LIST]
        call far [cs:drop_call]
        add sp, 2
        mov word [HELD], -1
        mov ax, ds              ; (the drop routine's AX is its own)
        sub ax, DGROUP_SEG - DROP_SEG
        mov [cs:sound_call + 2], ax  ; and the sound the game plays when a quest is done (with
        push word QUEST_SOUND   ;   "... receives N experience points!": its 5Dh command)
        call far [cs:sound_call]
        add sp, 2
        pop bx
.kept:
        mov dx, USE_DONE
        add [ss:bx + 34], dx
        cmp byte [cs:pick_text], 0
        je .out
        push word [ss:bx + 36]
        push word [ss:bx + 34]
        push bp
        mov bp, sp
        mov word [cs:show_text], pick_text
        call show_window
        pop bp
        pop ax                  ; the way back, as the overlay manager has left it
        pop dx
        mov bx, sp
        mov [ss:bx + 34], ax
        mov [ss:bx + 36], dx
        jmp .out
.go:    add [ss:bx + 34], dx
.out:   pop es
        popad
        iret

; whose turn it is (DS:4979h) has changed since last seen: count it, wait a moment for the
; companion's summary of the turn that ended (MSG_BUF) and show it; DS = the game's
turn_check:
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
        call rtc_begin
.wait:  mov ax, [cs:reply_seq]
        cmp ax, [cs:turn_seq]
        je .ready
        mov ax, [es:0x46C]
        sub ax, dx
        cmp ax, TURN_WAIT
        jae .late_reply_seq
        call rtc_waited         ; (the BIOS clock can stand still: the game's timer
        jnc .wait               ;   doesn't always pass its ticks on; at most 2 s by the real-time clock)
.late_reply_seq:
        jmp .out                ; no answer: the companion isn't reading
.ready: cmp byte [cs:msg_buf], 0
        je .out                 ; nothing to say about that turn
        mov word [cs:show_text], msg_buf
        call show_window
.out:   ret

; the text at CS:[SHOW_TEXT] in the game's dialogue window, with "Continue" to click;
; DS = the game's
show_window:
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
        push word 0             ; the text
        push cs
        push word [cs:show_text]
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
        ret

show_text dw 0                  ; the text SHOW_WINDOW shows
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
        mov eax, [0x11A4]       ; the USE screen is up: PROBE_WIN may redraw on this window
        mov [cs:use_win], eax
        call use_draw
        pop fs
        pop es
        popad
        iret

; PROBE_WIN: INT VEC_WIN replaces "xor ax,ax / pop si" (3 bytes: INT + NOP) at the end of the
; game's routine that brings a window to the front and redraws it (its window far pointer the
; argument, at the routine's BP+6), which repaints the USE screen's panels when a character or
; spell level is picked, after the LEVEL button's label (where PROBE_USE draws). For the USE
; screen's window, once PROBE_USE has drawn on it (not while the screen opens), the slots are
; drawn again. Everything is kept on the stack: drawing may run the routine again.
WIN_USE_SEG equ 0x40BC - 0x4356 ; the USE screen's window pointer is at this segment:0
probe_win:
        push bp
        mov bp, sp              ; BP+2 the interrupt frame, BP+8 the routine's saved SI
        sti
        pushad
        push es
        push fs
        mov di, [bp]            ; the routine's BP
        mov eax, [ss:di + 6]    ; its window
        or eax, eax
        jz .done
        cmp eax, [cs:use_win]
        jne .done               ; not a USE screen PROBE_USE has drawn on
        cmp eax, [0x11A4]
        jne .done               ; not the window on show
        mov bx, ds
        add bx, WIN_USE_SEG
        mov es, bx
        cmp eax, [es:0]
        jne .done               ; not the USE screen
        call use_draw
.done:  pop fs
        pop es
        popad
        xor ax, ax              ; the replaced "xor ax,ax"
        mov si, [bp + 8]        ; ... and "pop si": move the interrupt frame up over it
        push dx
        mov dx, [bp + 6]
        mov [bp + 8], dx
        mov dx, [bp + 4]
        mov [bp + 6], dx
        mov dx, [bp + 2]
        mov [bp + 4], dx
        pop dx
        mov sp, bp
        pop bp
        add sp, 2
        iret

use_win dd 0                    ; the USE screen's window, as PROBE_USE last saw it

use_draw:                       ; the selected character's slots in the USE screen's panel
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
.done:  ret
; PROBE_LOOK: INT VEC_LOOK replaces "mov si,ax / xor di,di" (4 bytes: INT + 2 NOPs) in the
; routine that fills the Look box (right-click to Look, then a monster in a fight), where the
; first of its four status rows have been drawn and AX says how many. Asks the companion
; for up to three short lines about the monster (LOOK_TEXT), prints them in the rows left
; with the game's text routine, as the box prints the monster's level, and moves the game's
; row count past them, so its own status lines follow in any row still free. If the
; companion also gave the whole description (LOOK_FULL), PROBE_TURN shows it in the dialogue
; window as the box closes (PROBE_UNLOOK).
LOOK_PATCH equ 0x5FCDA          ; DSUN.EXE offsets
LOOK_DRAW  equ 0x5FCB8          ; "lcall 0090h:0A40h" operand: the text routine
LOOK_ROWS  equ 4                ; the box's status rows: y = (row + 2) * 7 + 10h
probe_look:
        sti
        pushad
        push es
        mov si, sp              ; SS:SI: ES, then EDI, ESI, EBP, ESP, EBX, EDX, ECX, EAX, IP, CS, flags
        mov ax, [ss:si + 30]
        mov [cs:l_row], ax      ; the rows the game has used
        cmp word [cs:look_on], 0
        je .done
        mov bx, [bp + 0xA]      ; the combatant (BP: the Look routine's frame)
        mov [cs:look_who], bx
        mov byte [cs:look_text], 0
        mov byte [cs:look_full], 0
        inc word [cs:look_seq]
        xor ax, ax
        mov es, ax
        mov dx, [es:0x46C]      ; the BIOS timer
        call rtc_begin
.wait:  mov ax, [cs:look_reply]
        cmp ax, [cs:look_seq]
        je .ready
        mov ax, [es:0x46C]
        sub ax, dx
        cmp ax, TURN_WAIT
        jae .late_look_reply
        call rtc_waited         ; (the BIOS clock can stand still: the game's timer
        jnc .wait               ;   doesn't always pass its ticks on; at most 2 s by the real-time clock)
.late_look_reply:
        jmp .done               ; no answer: the companion isn't reading
.ready: mov es, [ss:si + 36]
        mov di, [ss:si + 34]
        sub di, 2               ; ES:DI = the patch
        mov eax, [es:di + LOOK_DRAW - LOOK_PATCH]
        mov [cs:l_draw], eax
        mov eax, [bp + 6]       ; the box's window
        mov [cs:l_win], eax
        mov di, look_text
.line:  cmp word [cs:l_row], LOOK_ROWS
        jae .full
        cmp byte [cs:di], 0
        je .full
        mov bx, l_line          ; the next line, up to "|", into L_LINE
.copy:  mov al, [cs:di]
        cmp al, '|'
        je .cut
        or al, al
        je .cut
        cmp bx, l_line + L_LINE_SIZE - 1
        jae .skip
        mov [cs:bx], al
        inc bx
.skip:  inc di
        jmp .copy
.cut:   mov byte [cs:bx], 0
        cmp byte [cs:di], '|'
        jne .draw
        inc di
.draw:  push di
        mov ax, [cs:l_row]
        add ax, 2
        imul ax, ax, 7
        add ax, 0x10
        push word 0x11          ; as the box prints LEVEL
        push word 0x1F
        push ax                 ; y
        push word 6             ; x
        push cs
        push word l_line
        push dword [cs:l_win]
        call far [cs:l_draw]
        add sp, 16
        pop di
        inc word [cs:l_row]
        jmp .line
.full:  cmp byte [cs:look_full], 0
        je .done
        mov byte [cs:look_pending], 1
.done:  mov si, sp              ; the replaced code: SI = the rows used, DI = 0
        mov ax, [cs:l_row]
        mov [ss:si + 6], ax
        mov dword [ss:si + 2], 0
        pop es
        popad
        iret

; PROBE_UNLOOK: INT VEC_UNLOOK replaces "mov word [0844h],270Fh" (6 bytes: INT + 4 NOPs) at the
; end of the routine that closes the Look box (the game forgets whom it was looking at). Does
; that, then shows the monster's whole description (LOOK_FULL) in the dialogue window.
probe_unlook:
        mov word [0x844], 0x270F  ; the replaced instruction (DS = the game's)
        sti
        pushad
        push es
        cmp byte [cs:look_pending], 0
        je .out
        cmp byte [cs:showing], 0
        jne .out
        mov byte [cs:look_pending], 0
        mov word [cs:show_text], look_full
        call show_window
.out:   pop es
        popad
        iret

; STATS: STATS_SIZE bytes for each party member, kept by the companion: +0 1 if in use, +1 THAC0
; with the main weapon (signed), +2 the five saves as the d20 needed now, +8 three words: the
; item numbers of the weapons ready, +14 three bytes: the THAC0 with each (signed), +17 1 for a
; thief (2 for a ranger: of the six, only move silently and hide in shadows count), +18 the six
; thief skills the panel shows, as they stand (equipment and effects too)
STATS_SIZE  equ 24
STATS_RANGER equ 2
STATS_FRESH equ 91              ; timer ticks (5 seconds)
STATS_WAIT  equ 9               ; ... (half a second): the longest a screen waits for fresh STATS
stats   times 4 * STATS_SIZE db 0

; A screen is being drawn: while the companion is keeping STATS, have it bring them up to date
; (an item just put on, say) and wait for that, once for all the screen's lines (not again
; within 2 timer ticks). The game stands still meanwhile, so its state is what's drawn.
stats_sync:
        push ax
        push dx
        push es
        xor ax, ax
        mov es, ax
        mov dx, [es:0x46C]
        mov ax, dx
        sub ax, [cs:sync_at]
        cmp ax, 2
        jb .out                 ; this screen's already
        mov ax, dx
        sub ax, [cs:stats_stamp]
        cmp ax, STATS_FRESH
        jae .out                ; the companion isn't running
        inc word [cs:stats_req]
        call rtc_begin
.wait:  mov ax, [cs:stats_reply]
        cmp ax, [cs:stats_req]
        je .done
        mov ax, [es:0x46C]
        sub ax, dx
        cmp ax, STATS_WAIT
        jae .done
        call rtc_waited         ; (as the waits for the companion: the BIOS clock can stand still)
        jnc .wait
.done:  mov ax, [es:0x46C]
        mov [cs:sync_at], ax
.out:   pop es
        pop dx
        pop ax
        ret

sync_at dw 0

; RTC_BEGIN, RTC_WAITED: a wait for the companion ends after its BIOS ticks, or, as the BIOS clock
; stands still while the game's timer handler keeps its ticks to itself (as in some fights), once
; the real-time clock's second has changed twice (1 to 2 seconds): never a hang.
rtc_begin:
        push ax
        call rtc_second
        mov [cs:w_sec], al
        mov byte [cs:w_flips], 0
        pop ax
        ret
rtc_waited:                             ; CF set: the wait is over
        push ax
        call rtc_second
        cmp al, [cs:w_sec]
        je .no
        mov [cs:w_sec], al
        inc byte [cs:w_flips]
        cmp byte [cs:w_flips], 2
        jb .no
        pop ax
        stc
        ret
.no:    pop ax
        clc
        ret
rtc_second:                             ; AL = the real-time clock's seconds (CMOS register 0)
        pushf
        cli
        mov al, 0
        out 0x70, al
        in al, 0x71
        popf
        ret
w_sec   db 0
w_flips db 0

; BX = a party member (0-3): CF clear and CS:BX = their STATS entry if the companion keeps it
; current, CF set if not
stats_for:
        cmp bx, 3
        ja .no
        push ax
        push es
        xor ax, ax
        mov es, ax
        mov ax, [es:0x46C]
        sub ax, [cs:stats_stamp]
        cmp ax, STATS_FRESH
        pop es
        pop ax
        jae .no
        imul bx, bx, STATS_SIZE
        add bx, stats
        cmp byte [cs:bx], 0
        je .no
        clc
        ret
.no:    stc
        ret

; THAC0 (AL) and the saves (sheet +37h..+3Bh at ES:SI) into C_VALS, or the companion's numbers
; for the character in C_WHO instead. Keeps ES, SI, DI.
c_load_stats:
        push bx
        mov [cs:c_vals], al
        mov eax, [es:si + 0x37]
        mov [cs:c_vals + 1], eax
        mov al, [es:si + 0x3B]
        mov [cs:c_vals + 5], al
        mov bx, [cs:c_who]
        call stats_sync
        call stats_for
        jc .own
        mov al, [cs:bx + 1]
        mov [cs:c_vals], al
        mov eax, [cs:bx + 2]
        mov [cs:c_vals + 1], eax
        mov al, [cs:bx + 6]
        mov [cs:c_vals + 5], al
.own:   pop bx
        ret

c_itoa_s:                       ; AL (signed) -> decimal at CS:DI, with "-" below 0; keeps BX, CX
        test al, al
        jns c_itoa
        mov byte [cs:di], '-'
        inc di
        neg al
        jmp c_itoa

; PROBE_WEAPON: INT VEC_WEAPON replaces "add sp,10h" (3 bytes: INT + NOP) straight after the
; routine that lists a creature's weapons (on the inventory screen, and in the Look box) has
; drawn one: its name, then its damage, AX lines from y = [BP+0Eh]. Does the add, then puts
; the THAC0 the companion worked out for that weapon at the right of its last line.
W_PATCH equ 0x7276E             ; DSUN.EXE offsets
W_DRAW  equ 0x72851             ; "lcall 0090h:0A40h" operand: the routine that draws the lines
W_X     equ 0x12A               ; (window coordinates: the lines start at 0ECh)
probe_weapon:
        pop word [cs:w_ip]
        pop word [cs:w_cs]
        pop word [cs:w_fl]
        add sp, 0x10            ; the replaced instruction
        sti
        pushad
        push es
        or ax, ax
        jz .done
        mov [cs:w_lines], ax
        mov bx, [bp + 0x0A]     ; the creature (its object number: the party's are 0-3)
        cmp bx, 3
        ja .done
        call stats_sync
        call stats_for
        jc .done
        mov si, [bp - 2]        ; the entry of the item list the weapon came from
        imul si, si, 10
        mov dx, [bp + si - 0x330]  ; its item number
        xor cx, cx
.find:  mov di, cx
        shl di, 1
        cmp [cs:bx + di + 8], dx
        je .found
        inc cx
        cmp cx, 3
        jb .find
        jmp .done
.found: mov di, cx
        mov al, [cs:bx + di + 14]
        mov di, w_text + 1
        call c_itoa_s
        mov es, [cs:w_cs]
        mov di, [cs:w_ip]
        mov eax, [es:di + W_DRAW - W_PATCH - 2]
        mov [cs:w_draw], eax
        mov ax, [cs:w_lines]
        dec ax
        imul ax, ax, 7
        add ax, [bp + 0x0E]     ; the weapon's last line
        push word [bp + 0x12]   ; the colours, as the routine draws its lines
        push word [bp + 0x10]
        push ax
        push word W_X
        push cs
        push word w_text
        push dword [bp + 6]     ; the window
        call far [cs:w_draw]
        add sp, 0x10
.done:  pop es
        popad
        push word [cs:w_fl]
        push word [cs:w_cs]
        push word [cs:w_ip]
        iret

w_ip    dw 0
w_cs    dw 0
w_fl    dw 0
w_lines dw 0
w_draw  dd 0
w_text  db 'T', 0, 0, 0, 0
c_who   dw 0
c_signed db 0

; RINGS: the game has rings (item type RING_TYPE, a plain "Ring") but nothing that makes
; one better AC or saves. The companion can put a Ring +1 in the arena; these two make its
; plus count, as a ring of protection's would.
RING_TYPE  equ 102
HELM_LEATHER equ 5              ; the helm item types: Helm, Dapartea's Helm; Helm of
HELM_METAL   equ 89             ; Contemplation; and a leather one no object uses (Helm of
HELM_OTHER   equ 109            ; Might, made by a script)
HELM_BONE    equ 117            ; (and the companion's bone helm, of TYPES)
FINGER     equ 4                ; the item's slot byte while worn on a finger (the left
FINGER2    equ 11               ; hand's, then the right's)
CLOAK      equ 12               ; ... and on the back
THINGS     equ 0xC36            ; the things table (3 bytes each: kind, index) in its segment
NO_THING   equ 0x270F
CREATURES  equ 0x1665           ; DS: far pointer to the creature records (3Ah bytes each)
ITEMS      equ 0x165D           ; DS: far pointer to the item records (15h bytes each)
ITEM_TYPES equ 0x1669           ; DS: far pointer to the item types (14h bytes each; +0Ah: 1 melee)
WS_MELEE   equ 0xFFFE           ; WS_TYPE: any melee weapon

; PROBE_RING_AC: INT VEC_RING_AC replaces "mov al,es:[bx+0Fh] / cbw" (5 bytes: INT + 3 NOPs)
; in the AC function, where ES:BX is a worn item's type and CX its number; bit 80h of AX
; says the type counts for AC (the plus less the type's AC). Does that, counting rings too.
probe_ring_ac:
        mov al, [es:bx+0x0F]
        cbw
        cmp cx, RING_TYPE
        jne .helm
        or al, 0x80
        iret
.helm:  cmp cx, HELM_LEATHER    ; a helm: AC 1 with RULE_HELMS (the game's are all 0), 0 without
        je .is
        cmp cx, HELM_METAL
        je .is
        cmp cx, HELM_OTHER
        je .is
        cmp cx, HELM_BONE
        je .is
        iret
.is:    push ax
        xor al, al
        test byte [cs:rules], RULE_HELMS
        jz .set
        inc al
.set:   mov [es:bx+0x12], al    ; (the type's AC, read next)
        pop ax
        iret

; PROBE_RING_SAVE: INT VEC_RING_SAVE replaces "xor si,si" (2 bytes) at the start of the
; function that adds up a saving throw's modifiers into SI, DI being the one saving. Starts
; SI at the plus of the rings they wear instead of 0.
probe_ring_save:
        push bp
        mov bp, sp              ; SS:BP+2 = our return address
        push ax
        push bx
        push cx
        push dx
        push es
        xor si, si
        les bx, [bp+2]
        mov ax, [es:bx+6]       ; the things table's segment: the code after the patch is
        call ring_plus          ; "mov bx,di / imul bx,bx,3 / mov ax,<segment>"
        pop es
        pop dx
        pop cx
        pop bx
        pop ax
        pop bp
        iret

ring_plus:                      ; DS = the game's, AX = the things table's segment, DI = a
        mov [cs:r_things], ax   ; creature's thing: SI += the pluses of the rings it wears
        mov es, ax
        mov bx, di
        imul bx, bx, 3
        cmp byte [es:bx+THINGS], 2
        jne .done               ; not a creature
        mov ax, [es:bx+THINGS+1]
        mov [cs:r_who], ax
        mov word [cs:ws_slot], FINGER
        mov word [cs:ws_type], RING_TYPE
        call worn_scan
        add si, [cs:ws_plus]
        mov ax, [cs:r_who]
        mov word [cs:ws_slot], FINGER2
        call worn_scan
        add si, [cs:ws_plus]
        mov ax, [cs:types_first]  ; and a cloak of protection's (the second of TYPES), worn
        or ax, ax
        jz .done
        inc ax
        mov [cs:ws_type], ax
        mov word [cs:ws_slot], CLOAK
        mov ax, [cs:r_who]
        call worn_scan
        add si, [cs:ws_plus]
.done:  ret

; The items creature AX (DS = the game's, R_THINGS the things table's segment) wears in slot
; WS_SLOT, of type WS_TYPE (0FFFFh: any): WS_COUNT of them, their positive pluses adding up to
; WS_PLUS. Keeps SI, DI, BP.
worn_scan:
        push cx
        imul ax, ax, 0x3A
        mov [cs:r_creature], ax
        mov word [cs:ws_count], 0
        mov word [cs:ws_plus], 0
        mov cx, 8               ; its item lists, each a thing: +8, +0Ah, +0Ch
.list:  les bx, [CREATURES]
        add bx, [cs:r_creature]
        add bx, cx
        mov dx, [es:bx]
        cmp dx, NO_THING
        jae .next
        mov es, [cs:r_things]
        mov bx, dx
        imul bx, bx, 3
        cmp byte [es:bx+THINGS], 1
        jne .next               ; not an item
        mov dx, [es:bx+THINGS+1]
        mov byte [cs:r_left], 100
.item:  cmp dx, NO_THING
        jae .next
        les bx, [ITEMS]
        mov ax, dx
        imul ax, ax, 0x15
        add bx, ax
        mov al, [es:bx+0x11]
        cmp al, [cs:ws_slot]
        jne .on
        mov ax, [cs:ws_type]
        cmp ax, 0xFFFF
        je .match
        cmp ax, WS_MELEE
        je .melee
        cmp [es:bx+0x0A], ax
        jne .on
        jmp .match
.melee: push es               ; WS_MELEE: a melee weapon (its type's class 1)
        push bx
        mov ax, [es:bx+0x0A]
        imul ax, ax, 0x14
        les bx, [ITEM_TYPES]
        add bx, ax
        cmp byte [es:bx+0x0A], 1
        pop bx
        pop es
        jne .on
.match: inc word [cs:ws_count]
        mov al, [es:bx+0x14]    ; the plus
        cbw
        or ax, ax
        jle .on
        add [cs:ws_plus], ax
.on:    mov dx, [es:bx+4]       ; the next item in the list
        dec byte [cs:r_left]
        jnz .item
.next:  add cx, 2
        cmp cx, 0x0E
        jb .list
        pop cx
        ret

r_things   dw 0
r_creature dw 0
r_left     db 0
r_who      dw 0
ws_slot    dw 0
ws_type    dw 0
ws_count   dw 0
ws_plus    dw 0

; RULES (set by the companion, from its Options): a helm counts AC 1, boots add 1 to movement
; in a fight
RULE_HELMS equ 1
RULE_BOOTS equ 2
RULE_TWO_WEAPONS equ 4
RULE_SPELL_SAVE equ 8           ; (the companion writes the game's save table for this one)
RULE_NO_DOUBLE equ 16
RULE_CATS_GRACE equ 32          ; (the companion also gives Flaming Sphere Strength's record and the name)
RULE_STEALTH equ 64             ; (the companion rolls the hiding and moving silently, and sets STEALTH)
RULE_LEVEL_10 equ 128          ; class levels go up to 10, not 9
RULE_THIEF_TABLE equ 256        ; thief skills from AD&D's table and Dark Sun's DEX adjustments
RULE_HALF_GIANT equ 512         ; half-giants wield two-handed weapons in one hand
FOOT       equ 13               ; the item's slot byte while worn on the feet
THINGS_SEG equ 0x3972 - 0x4356  ; the things table's segment, relative to DS

; PROBE_MOVE: INT VEC_MOVE replaces "mov es:[bx+22Bh],ax" (5 bytes: INT + 3 NOPs) where a
; creature's turn in a fight starts: AX = its movement for the turn (its Move x 10), SI the
; creature. Does the move, with 10 more for boots on its feet when RULE_BOOTS is on.
probe_move:
        test byte [cs:rules], RULE_BOOTS
        jz .store
        push ax
        push bx
        push cx
        push dx
        push es
        mov ax, ds
        add ax, THINGS_SEG
        mov [cs:r_things], ax
        mov ax, si
        mov word [cs:ws_slot], FOOT
        mov word [cs:ws_type], 0xFFFF
        call worn_scan
        pop es
        pop dx
        pop cx
        pop bx
        pop ax
        cmp word [cs:ws_count], 0
        je .store
        add ax, 10
.store: mov [es:bx+0x22B], ax
        iret

; PROBE_TWO: INT VEC_TWO replaces "neg ax / mov dx,ax / or dx,dx / jge +2 / xor dx,dx" (10
; bytes: INT + 8 NOPs) in the routine that gives an attack's to-hit adjustment for two weapons
; ready, after the call that reads the attacker's DEX in the game's initiative table (AX), for
; a non-ranger; [BP+0Ah] is the attack's item, CX the attacker's object. Leaves the
; adjustment in DX: the game's, -AX and no less than 0; with RULE_TWO_WEAPONS, AD&D's: -2 (the
; item in the right hand) or -4 (in the left) plus AX (the same numbers as the reaction
; adjustment), no more than 0, and only with a melee weapon in the other hand too (else 0:
; a two-handed weapon, a shield, a sling or bow in the missile slot don't count).
RIGHT_HAND equ 3
LEFT_HAND  equ 10
probe_two:
        test byte [cs:rules], RULE_TWO_WEAPONS
        jnz .rule
        neg ax
        mov dx, ax
        or dx, dx
        jge .done
        xor dx, dx
.done:  iret
.rule:  push bx
        push es
        push cx
        mov [cs:t_adjust], ax
        xor dx, dx
        mov bx, [bp+0x0A]
        cmp bx, NO_THING
        jae .out
        imul bx, bx, 0x15
        mov ax, bx
        les bx, [ITEMS]
        add bx, ax
        mov al, [es:bx+0x11]    ; the attack's hand, and the other
        mov dx, -2
        mov ah, LEFT_HAND
        cmp al, RIGHT_HAND
        je .hand
        mov dx, -4
        mov ah, RIGHT_HAND
        cmp al, LEFT_HAND
        je .hand
        xor dx, dx
        jmp .out
.hand:  mov [cs:t_base], dx
        mov [cs:ws_slot], ah
        mov byte [cs:ws_slot+1], 0
        mov word [cs:ws_type], WS_MELEE
        mov ax, ds
        add ax, THINGS_SEG
        mov [cs:r_things], ax
        mov es, ax
        mov bx, cx
        imul bx, bx, 3
        xor dx, dx
        cmp byte [es:bx+THINGS], 2
        jne .out                ; not a creature
        mov ax, [es:bx+THINGS+1]
        call worn_scan
        xor dx, dx
        cmp word [cs:ws_count], 0
        je .out                 ; nothing to fight with in the other hand
        mov dx, [cs:t_base]
        add dx, [cs:t_adjust]
        jle .out
        xor dx, dx
.out:   pop cx
        pop es
        pop bx
        iret
t_base   dw 0
t_adjust dw 0

; PROBE_DOUBLE: INT VEC_DOUBLE replaces "shl al,1" (2 bytes), where the saving throw doubles
; its d20 against fire, cold and electricity spells; not with RULE_NO_DOUBLE.
probe_double:
        test byte [cs:rules], RULE_NO_DOUBLE
        jnz .done
        shl al, 1
.done:  iret

; PROBE_LEVEL: INT VEC_LEVEL replaces "cmp byte es:[bx+24h],9" (5 bytes: INT + 3 NOPs) in the
; two places the game holds a class level (ES:BX+24h, a sheet's) against its cap of 9: where a
; character goes up a level (only while below it) and where View Character shows the XP for the
; next level (not at it). With RULE_LEVEL_10 the cap is 10: the game's XP tables, hit points,
; THAC0, saves, spell slots and thief skills all go on past 9 (the tables have 20 levels, the
; rest are formulas). RETF 2 keeps the compare's flags.
probe_level:
        sti
        push ax
        mov al, 9
        test byte [cs:rules], RULE_LEVEL_10
        jz .cmp
        inc al
.cmp:   cmp [es:bx+0x24], al
        pop ax
        retf 2

; A thief's hit dice. The game keeps one "dice up to this level" for thieves and psionicists
; together (9: after it, +2 a level), but an AD&D thief rolls a d6 up to 10th (a psionicist
; stops at 9th). With RULE_LEVEL_10 a thief's goes to 10, in the two places it counts.
THIEF_CLASS equ 17
; PROBE_HD_ROLL: INT VEC_HD_ROLL replaces "mov al,es:[bx+1]" (5 bytes: INT + 3 NOPs) where a new
; level's hit points are a roll or the fixed gain: ES:BX the class's hit point group, the
; game's [BP+8] the class.
probe_hd_roll:
        mov al, [es:bx+1]
        test byte [cs:rules], RULE_LEVEL_10
        jz .done
        cmp al, 9
        jne .done
        cmp word [bp+8], THIEF_CLASS
        jne .done
        inc al
.done:  iret

; PROBE_HD_CON: INT VEC_HD_CON replaces "cmp al,es:[bx+1]" (5 bytes: INT + 3 NOPs) where the game
; counts the levels CON's hit point bonus applies to: AL a class's level, ES:BX its group, the
; game's [BP-4] the sheet (far) and CX which of its classes. RETF 2 keeps the compare's flags.
probe_hd_con:
        sti
        push dx
        mov dl, [es:bx+1]
        test byte [cs:rules], RULE_LEVEL_10
        jz .cmp
        cmp dl, 9
        jne .cmp
        push es
        push bx
        les bx, [bp-4]
        add bx, cx
        cmp byte [es:bx+0x21], THIEF_CLASS
        pop bx
        pop es
        jne .cmp
        inc dl
.cmp:   cmp al, dl
        pop dx
        retf 2

; PROBE_THIEF_SKILL: INT VEC_THIEF_SKILL, then "jc" past the game's DEX formula, replaces
; "mov ax,si / shl ax,2 / add dx,ax / mov si,dx" (9 bytes) in the game's thief skill routine,
; where DX is the skill's base plus the race's adjustment, SI the thief level, ES:0 the game's
; thief tables (the base at +skill), and the game's [BP+8] the skill, [BP-0Ch] DEX. Without
; RULE_THIEF_TABLE (or a thief level), the game's sum (SI = DX + 4 a level), CF clear: on to
; the game's DEX formula. With it, SI = AD&D's average for the level (THIEF_TABLE, levels past
; 10 as 10) + the race's adjustment + Dark Sun's DEX adjustment (DEX_TABLE, DEX 9-22), CF set:
; past the game's DEX formula, to its armour and effects (dscompanion/game.py does the same sums).
probe_thief_skill:
        sti
        test word [cs:rules], RULE_THIEF_TABLE
        jz .game
        cmp si, 1
        jl .game
        push ax
        push bx
        mov bx, [bp+8]
        and bx, 7
        mov al, [es:bx]         ; the game's base, out
        cbw
        sub dx, ax
        mov ax, si
        cmp ax, 10
        jbe .level
        mov ax, 10
.level: dec ax
        imul bx, bx, 10
        add bx, ax
        mov al, [cs:thief_table+bx]
        mov ah, 0
        add dx, ax
        mov bx, [bp+8]
        and bx, 7
        cmp bx, 5               ; DEX adjusts the first five
        jae .done
        mov ax, [bp-0Ch]
        cmp ax, 9
        jge .low
        mov ax, 9
.low:   cmp ax, 22
        jle .high
        mov ax, 22
.high:  sub ax, 9
        imul ax, ax, 5
        add bx, ax
        mov al, [cs:dex_table+bx]
        cbw
        add dx, ax
.done:  mov si, dx
        pop bx
        pop ax
        push bp
        mov bp, sp
        or word [bp+6], 1       ; CF in the flags IRET restores: past the game's DEX formula
        pop bp
        iret
.game:  shl si, 2
        add si, dx
        push bp
        mov bp, sp
        and word [bp+6], 0FFFEh
        pop bp
        iret
; PROBE_TWO_HANDED: INT VEC_TWO_HANDED replaces "test byte es:[bx+0Fh],40h" (5 bytes: INT + 3
; NOPs), the two-handed bit of an item type (ES:BX), where the inventory screen puts a weapon in
; a hand: of the other hand's ("Two handed weapon in use") and of the one going in ("Need two
; free hands"). With RULE_HALF_GIANT, for a half-giant on show the answer is "not two-handed"
; (ZF set); otherwise the game's test. RETF 2 keeps the flags. (The game's own check that both
; hands don't hold heavy weapons, over 30 each, still stands.)
WHO_SEG equ USE_WHO_SEG          ; the segment of the character on show's number (+25Bh), from DS
                                ; (the overlay's code says 0348h, which its loader relocates there)
HALF_GIANT equ 5
probe_two_handed:
        sti
        test word [cs:rules], RULE_HALF_GIANT
        jz .test
        push ax
        push es
        push bx
        mov ax, ds
        add ax, WHO_SEG
        mov es, ax
        imul ax, [es:0x25B], 0x47
        les bx, [0x1661]
        add bx, ax              ; ES:BX = the sheet of the character on show
        cmp byte [es:bx + 0x18], HALF_GIANT
        pop bx
        pop es
        pop ax
        jne .test
        cmp ax, ax              ; ZF: not two-handed, for a half-giant
        retf 2
.test:  test byte [es:bx + 0x0F], 0x40
        retf 2

; PROBE_SPELL_TEXT: INT VEC_SPELL_TEXT replaces "add sp,0Ch" (3 bytes: INT + NOP) after the game
; reads a spell's description (RESOURCE.GFF's SPIN chunk DI, the spell's number + 1) into the
; buffer at the game's [BP-8] (far), AX its length or FFFFh. With RULE_CATS_GRACE, Flaming
; Sphere's (SPIN 15) is Cat's Grace's instead, in the game's words for Strength's.
SPIN_SPHERE equ 15
probe_spell_text:
        pop word [cs:n_ip]
        pop word [cs:n_cs]
        pop word [cs:n_fl]
        add sp, 0x0C
        push word [cs:n_fl]
        push word [cs:n_cs]
        push word [cs:n_ip]
        test byte [cs:rules], RULE_CATS_GRACE
        jz .out
        cmp di, SPIN_SPHERE
        jne .out
        cmp ax, 0xFFFF
        je .out
        push cx
        push si
        push di
        push ds
        push es
        les di, [bp-8]
        push cs
        pop ds
        mov si, grace_text
        mov cx, GRACE_TEXT_LEN
        cld
        rep movsb
        pop es
        pop ds
        pop di
        pop si
        pop cx
        mov ax, GRACE_TEXT_LEN - 1  ; (its length, as the game's read gives it)
.out:   iret
grace_text:
        db "CAT'S GRACE:  Raises the target's dexterity by 1 to 6 pts. Maximum dexterity is 24.", 13, 10, 0
GRACE_TEXT_LEN equ $ - grace_text

; PROBE_CHUNK_ID: INT VEC_CHUNK_ID replaces "cmp [9Ch],sp" (4 bytes: INT + 2 NOPs; the stack
; check) at the start of the game's two routines that load a GFF chunk, whose [BP+6] is the
; chunk's type and [BP+0Ah] its number (dwords). With RULE_CATS_GRACE, and the companion's copy
; of RESOURCE.GFF open, Flaming Sphere's icon (ICON 21014) is asked for as Cat's Grace's
; (GRACE_ICON, which only the copy has). Then the stack check, with the routine's SP; RETF 2
; keeps its flags.
SPHERE_ICON equ 21014
GRACE_ICON  equ 21900
probe_chunk_id:
        sti                     ; (RETF 2 keeps these flags: interrupts on, as the game had them)
        test byte [cs:rules], RULE_CATS_GRACE
        jz .check
        cmp word [cs:resources_on], 1
        jne .check
        cmp dword [bp+6], 0x4E4F4349    ; 'ICON'
        jne .check
        cmp dword [bp+0x0A], SPHERE_ICON
        jne .check
        mov dword [bp+0x0A], GRACE_ICON
.check: push ax
        mov ax, sp
        add ax, 8               ; (the routine's SP: past this push and INT's IP, CS and flags)
        cmp [0x9C], ax
        pop ax
        retf 2

; AD&D's average thief skills, levels 1-10, a row per skill (game.AD_D_THIEF)
thief_table:
        db 30, 35, 40, 45, 50, 55, 60, 65, 70, 80     ; pick pockets
        db 25, 29, 33, 37, 42, 47, 52, 57, 62, 67     ; open locks
        db 20, 25, 30, 35, 40, 45, 50, 55, 60, 65     ; find/remove traps
        db 15, 21, 27, 33, 40, 47, 55, 62, 70, 78     ; move silently
        db 10, 15, 20, 25, 31, 37, 43, 49, 56, 63     ; hide in shadows
        db 10, 10, 15, 15, 20, 20, 25, 25, 30, 30     ; hear noise
        db 85, 86, 87, 88, 90, 92, 94, 96, 98, 99     ; climb walls
        db 0, 0, 0, 20, 25, 30, 35, 40, 45, 50        ; read languages
; Dark Sun's DEX adjustments, DEX 9-22, a row per DEX: pick, open, traps, move, hide (game.DEX_ADJUST)
dex_table:
        db -15, -10, -10, -20, -10
        db -10, -5, -10, -15, -5
        db -5, 0, -5, -10, 0
        db 0, 0, 0, -5, 0
        db 0, 0, 0, 0, 0
        db 0, 0, 0, 0, 0
        db 0, 0, 0, 0, 0
        db 0, 5, 0, 0, 0
        db 5, 10, 0, 5, 5
        db 10, 15, 5, 10, 10
        db 15, 20, 10, 15, 15
        db 20, 25, 12, 20, 17
        db 25, 27, 15, 25, 20
        db 27, 30, 17, 30, 22

; PROBE_DOS_OPEN: the DOS services (INT 21h), hooked. Opening a file (AH=3Dh) whose name ends in
; one of COPIES' (SEGOBJEX.GFF, the game's objects and their pictures; RESOURCE.GFF, its screens'
; pictures and texts; GPLDATA.GFF, its scripts; RGN29.GFF, the slave pens) opens the companion's
; copy instead (D:\..., which the launcher writes with
; the companion's icons added; the game folder is never changed), and notes that it has; with no
; copy there, the game's own. Everything else goes on to DOS.
OBJ_NAME_LEN equ 12
probe_dos_open:
        cmp ah, 3Dh
        jne .chain
        push ax
        push bx
        push cx
        push si
        push di
        mov si, dx
        mov cx, 128
.end:   cmp byte [si], 0
        je .at_end
        inc si
        loop .end
        jmp .no
;
; Each copy's name (its length first) is matched against the end of the path, where it starts the
; path or follows a \, : or /.
.at_end:
        mov ax, si
        sub ax, dx              ; AX: the path's length
        mov bx, copies
.file:  mov cl, [cs:bx]         ; this copy's name length (0: no more)
        xor ch, ch
        jcxz .no
        cmp ax, cx
        jb .next
        push ax
        push si
        sub si, cx              ; where the name would start
        cmp ax, cx
        je .compare             ; (the path is just the name)
        mov al, [si - 1]
        cmp al, '\'
        je .compare
        cmp al, ':'
        je .compare
        cmp al, '/'
        jne .differ
.compare:
        lea di, [bx + 1]
.cmp:   mov al, [si]
        cmp al, 'a'
        jb .upper
        cmp al, 'z'
        ja .upper
        sub al, 20h
.upper: cmp al, [cs:di]
        jne .differ
        inc si
        inc di
        loop .cmp
        pop si
        pop ax
        jmp .found
.differ:
        pop si
        pop ax
.next:  add bx, COPY_SIZE
        jmp .file
.found: mov [cs:copy_at], bx
        pop di
        pop si
        pop cx
        pop bx
        pop ax
        sti                     ; (RETF 2 keeps these flags: interrupts on, as the game had them)
        push ax                 ; (the game's AX, for its own file if there's no copy)
        push ds
        push dx
        push cs
        pop ds
        mov dx, [cs:copy_at]
        add dx, 1 + OBJ_NAME_LEN  ; its copy's path
        pushf
        call far [cs:old21]
        pop dx
        pop ds
        jc .own
        pop word [cs:obj_scratch]  ; (POP keeps the flags: CF clear, AX the handle)
        push bx
        mov bx, [cs:copy_at]
        mov bx, [cs:bx + 1 + OBJ_NAME_LEN + COPY_PATH]  ; (its flag: set to 1)
        mov word [cs:bx], 1
        pop bx
        retf 2
.own:   pop ax
        jmp .chain
.no:    pop di
        pop si
        pop cx
        pop bx
        pop ax
.chain: jmp far [cs:old21]
old21       dd 0
obj_scratch dw 0
copy_at     dw 0
resources_on dw 0               ; 1 once the game has opened D:\RESOURCE.GFF (PROBE_CHUNK_ID)
scripts_on dw 0                 ; 1 once the game has opened D:\GPLDATA.GFF (Kalzith's conversation)
region_on dw 0                  ; 1 once the game has opened D:\RGN29.GFF (Kalzith in the pens)
; the files with copies: the name's length, the game's name (up to 12 letters), the copy's path,
; the flag set when opened
COPY_PATH equ 16
COPY_SIZE equ 1 + OBJ_NAME_LEN + COPY_PATH + 2
%macro COPY 3
        db %strlen(%1), %1
        times OBJ_NAME_LEN - %strlen(%1) db 0
        db %2
        times COPY_PATH - %strlen(%2) db 0
        dw %3
%endmacro
copies:
        COPY 'SEGOBJEX.GFF', 'D:\SEGOBJEX.GFF', objects_on
        COPY 'RESOURCE.GFF', 'D:\RESOURCE.GFF', resources_on
        COPY 'GPLDATA.GFF', 'D:\GPLDATA.GFF', scripts_on
        COPY 'RGN29.GFF', 'D:\RGN29.GFF', region_on
        db 0

; CAT'S GRACE (RULE_CATS_GRACE): Flaming Sphere (spell 14), given Strength's record and the
; name by the companion, works as Strength does but for DEX: its own effect (54, a number the
; game leaves unused) holds the 1d6, which the routine that works out a creature's abilities
; adds to DEX, keeping it between 3 and 24.
GRACE_SPELL    equ 14
STRENGTH_SPELL equ 23
GRACE_EFFECT   equ 54
ADRENALIN      equ 0x94         ; the psionic Adrenalin Control, which Strength's code also serves

; PROBE_GRACE_CAST: INT VEC_GRACE_CAST replaces "mov ax,[bp+0Eh] / mov [bp-1Ah],ax" (6 bytes:
; INT + 4 NOPs) where the code for spells with handlers of their own picks the handler by the
; spell's number: Cat's Grace goes to Strength's.
probe_grace_cast:
        mov ax, [bp+0x0E]
        test byte [cs:rules], RULE_CATS_GRACE
        jz .store
        cmp ax, GRACE_SPELL
        jne .store
        mov ax, STRENGTH_SPELL
.store: mov [bp-0x1A], ax
        iret

; PROBE_GRACE_EFFECT: INT VEC_GRACE_EFFECT replaces Strength's handler choosing its effect
; (19 bytes: INT + 17 NOPs): Adrenalin Control 42h, Strength 43h, and Cat's Grace its own.
probe_grace_effect:
        mov word [bp-0x14], 0x43
        cmp word [bp+0x0E], ADRENALIN
        jne .grace
        mov word [bp-0x14], 0x42
        iret
.grace: test byte [cs:rules], RULE_CATS_GRACE
        jz .out
        cmp word [bp+0x0E], GRACE_SPELL
        jne .out
        mov word [bp-0x14], GRACE_EFFECT
.out:   iret

; PROBE_GRACE_ABILITY: INT VEC_GRACE_ABILITY replaces "mov [bp-0Ah],ax / mov cx,7" (6 bytes:
; INT + 4 NOPs) in the routine that works out a creature's abilities, as it looks at one of its
; effects (AX its number; ES:BX the effect, its amount at +10Fh): Cat's Grace adds the amount
; to DEX in its sums (words from [BP-342h], STR first), as Strength's adds to STR.
probe_grace_ability:
        mov [bp-0x0A], ax
        mov cx, 7
        cmp ax, GRACE_EFFECT
        jne .out
        push ax
        mov al, [es:bx+0x10F]
        cbw
        add ax, [bp-0x340]
        cmp ax, 24
        jle .low
        mov ax, 24
.low:   cmp ax, 3
        jge .set
        mov ax, 3
.set:   mov [bp-0x340], ax
        pop ax
.out:   iret

; NAMES: the game's name table (GPLDATA's NAME chunk: 322 names of 25 bytes, which items name
; by number) gets NAMES_EXTRA more, for the companion's own items (the Ring of Protection, the
; Thieves' Tools...). Where the game reserves memory for the chunk (as it starts, and as a game
; is loaded) PROBE_NAMES_SIZE makes the room for them; once it has read the chunk in,
; PROBE_NAMES_FILL copies EXTRA_NAMES after the game's own. Nothing in the game limits the
; numbers to its own 322.
NAMES_OWN    equ 0x142
NAME_SIZE    equ 25
NAMES_EXTRA  equ 32
NAMES_PTR    equ 0x166D         ; DS: far pointer to the name table

; PROBE_NAMES_SIZE: INT VEC_NAMES_SIZE replaces "push dword 1" (3 bytes: INT + NOP) just before
; the game reserves memory for the NAME chunk, its size the dword at [BP-4]: adds the room,
; then does the push (under the interrupt's return frame).
probe_names_size:
        add word [bp-4], NAMES_EXTRA * NAME_SIZE
        adc word [bp-2], 0
        pop word [cs:n_ip]
        pop word [cs:n_cs]
        pop word [cs:n_fl]
        push dword 1
        push word [cs:n_fl]
        push word [cs:n_cs]
        push word [cs:n_ip]
        iret

; PROBE_NAMES_FILL: INT VEC_NAMES_FILL replaces "add sp,0Ch" (3 bytes: INT + NOP) after the call
; that reads the NAME chunk into the table (AX 0: read). Does the add, then, if it was read,
; copies EXTRA_NAMES after the game's names and notes the table in NAMES_PTR.
probe_names_fill:
        pop word [cs:n_ip]
        pop word [cs:n_cs]
        pop word [cs:n_fl]
        add sp, 0x0C
        push word [cs:n_fl]
        push word [cs:n_cs]
        push word [cs:n_ip]
        or ax, ax
        jnz .out
        push cx
        push si
        push di
        push ds
        push es
        les di, [NAMES_PTR]
        mov [cs:names_ptr], di
        mov [cs:names_ptr+2], es
        add di, NAMES_OWN * NAME_SIZE
        push cs
        pop ds
        mov si, extra_names
        mov cx, NAMES_EXTRA * NAME_SIZE
        cld
        rep movsb
        pop es
        pop ds
        pop di
        pop si
        pop cx
.out:   iret
n_ip    dw 0
n_cs    dw 0
n_fl    dw 0

; TYPES: the game's item types (GPLDATA's IT1R chunk, 20 bytes each, which items name by
; number), read in just before the names, get TYPES_EXTRA more in the same way: for the
; companion's own items that no type of the game's fits (a metal short sword, a cloak of
; protection). Nothing in the game limits the numbers to its own.
TYPE_SIZE   equ 20
TYPES_EXTRA equ 8
TYPES_PTR   equ 0x1669          ; DS: far pointer to the item types

; PROBE_TYPES_SIZE: INT VEC_TYPES_SIZE replaces "push dword 1" (3 bytes: INT + NOP) before the
; game reserves memory for the IT1R chunk, its size the dword at [BP-4]: adds the room.
probe_types_size:
        add word [bp-4], TYPES_EXTRA * TYPE_SIZE
        adc word [bp-2], 0
        pop word [cs:n_ip]
        pop word [cs:n_cs]
        pop word [cs:n_fl]
        push dword 1
        push word [cs:n_fl]
        push word [cs:n_cs]
        push word [cs:n_ip]
        iret

; PROBE_TYPES_FILL: INT VEC_TYPES_FILL replaces "add sp,0Ch" (3 bytes: INT + NOP) after the
; call that reads the chunk in (AX 0: read). Does the add, then, if it was read, copies
; EXTRA_TYPES after the game's own (the room made, [BP-4], less theirs) and notes where.
probe_types_fill:
        pop word [cs:n_ip]
        pop word [cs:n_cs]
        pop word [cs:n_fl]
        add sp, 0x0C
        push word [cs:n_fl]
        push word [cs:n_cs]
        push word [cs:n_ip]
        or ax, ax
        jnz .out
        push ax
        push cx
        push dx
        push si
        push di
        push ds
        push es
        les di, [TYPES_PTR]
        mov [cs:types_ptr], di
        mov [cs:types_ptr+2], es
        mov ax, [bp-4]
        sub ax, TYPES_EXTRA * TYPE_SIZE
        add di, ax              ; after the game's own
        xor dx, dx
        mov cx, TYPE_SIZE
        div cx
        mov [cs:types_first], ax
        push cs
        pop ds
        mov si, extra_types
        mov cx, TYPES_EXTRA * TYPE_SIZE
        cld
        rep movsb
        pop es
        pop ds
        pop di
        pop si
        pop dx
        pop cx
        pop ax
.out:   iret
; the types, numbered from the game's count (115): the companion's (the same as TYPES in
; dscompanion/npcitems.py), the rest unused
extra_types:
        ; a metal short sword: the metal long sword's type (63), 1d6
        db 0x01, 0x00, 0x30, 0x00, 0x1E, 0x00, 0xFA, 0x00, 0x04, 0x05, 0x01, 0x01
        db 0x06, 0x01, 0x00, 0x00, 0x72, 0x16, 0x00, 0x01
        ; a cloak of protection: the Cloak's type (65), no material shown, its plus counting
        ; for AC (bit 80h of +0Fh, as armour's) with an AC of its own of 0
        db 0x00, 0x00, 0x00, 0x00, 0x0A, 0x00, 0x0A, 0x00, 0x40, 0x08, 0x00, 0x00
        db 0x00, 0x00, 0x00, 0x80, 0xFF, 0x1F, 0x00, 0x01
        ; a bone helm: the Helm's type (5), of bone (to go with the bone scale armour), and like
        ; it for the classes that can wear it (+10h: no thieves, where the Helm allows them)
        db 0x00, 0x00, 0x00, 0x00, 0x0F, 0x00, 0xFA, 0x00, 0x01, 0x06, 0x00, 0x00
        db 0x00, 0x00, 0x00, 0x80, 0x6F, 0x12, 0x00, 0x00
        times (TYPES_EXTRA - 3) * TYPE_SIZE db 0
; the names, numbered from NAMES_OWN (322): the companion's items' (the same as the companion's
; NAMES in dscompanion/names.py), the rest blank until it writes more
extra_names:
        db "Ring/Protection"
        times NAME_SIZE - 15 db 0
        db "Thieves' Tools"
        times NAME_SIZE - 14 db 0
        db "Short Sword"                ; (Kurzak's, of type TYPES' first)
        times NAME_SIZE - 11 db 0
        db "Cloak/Protectn"             ; (Pehtucl's, the game's way of shortening)
        times NAME_SIZE - 14 db 0
        db "Ring/Protection"            ; (Pehtucl's ring: the arena's is the first; their icons differ)
        times NAME_SIZE - 15 db 0
        times (NAMES_EXTRA - 5) * NAME_SIZE db 0

; STEALTH (RULE_STEALTH): a thief who starts a turn with no enemy next to them may hide in
; shadows and move silently up to someone; the companion rolls both and, when both succeed,
; sets the thief's bit in STEALTH. Their next attack then counts as one from behind, and so
; as a backstab when the game's own conditions for one hold; the bit is cleared (attacking
; gives the thief away).
;
; PROBE_STEALTH: INT VEC_STEALTH replaces "push word [bp-1Ah]" (3 bytes: INT + NOP) in the
; routine that sets up an attack, straight after it has worked out whether the attacker (SI)
; is behind the target (DI) and whether that makes a backstab: [BP-1Ah] from behind (+2 to
; hit, the target's DEX and shield don't count), [BP-24h] a backstab (+2 more, and the damage
; multiplied), [BP-20h] the THAC0 they lower; [BP-1Ch] set when the target is an object, which
; has no back. Does the push (under the interrupt's return frame).
probe_stealth:
        pop word [cs:s_ip]
        pop word [cs:s_cs]
        pop word [cs:s_fl]
        test byte [cs:rules], RULE_STEALTH
        jz .push
        cmp si, 3
        ja .push
        btr word [cs:stealth], si
        jnc .push
        inc word [cs:stealth_used]
        cmp word [bp-0x1C], 0
        jne .push
        push ax
        push bx
        push es
        cmp word [bp-0x1A], 0
        jne .stab
        mov word [bp-0x1A], 1
        sub word [bp-0x20], 2
.stab:  cmp word [bp-0x24], 0
        jne .done
        ; the game's own conditions: a thief (the sheet's word +12h, bit 400h), in melee
        ; ([BP+0Eh] 1), with a weapon whose type weighs 40 or less (the type's word +4)
        mov ax, [bp-0x12]
        imul ax, ax, 0x47
        les bx, [0x1661]
        add bx, ax
        test word [es:bx+0x12], 0x400
        jz .done
        cmp word [bp+0x0E], 1
        jne .done
        mov ax, [bp-4]
        imul ax, ax, 0x14
        les bx, [0x1669]
        add bx, ax
        cmp word [es:bx+4], 0x28
        jg .done
        sub word [bp-0x20], 2
        mov word [bp-0x24], 1
.done:  pop es
        pop bx
        pop ax
.push:  push word [bp-0x1A]
        push word [cs:s_fl]
        push word [cs:s_cs]
        push word [cs:s_ip]
        iret
s_ip    dw 0
s_cs    dw 0
s_fl    dw 0

L_LINE_SIZE equ 24
LOOK_SIZE   equ 80
LOOK_FULL_SIZE equ 700
l_row   dw 0
l_draw  dd 0
l_win   dd 0
l_line  times L_LINE_SIZE db 0
look_pending db 0
look_text times LOOK_SIZE db 0
look_full times LOOK_FULL_SIZE db 0

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

; SHADOWS (SHADOWS_ON): every figure the companion marks (SHADOW_TAB) casts a see-through shadow
; on the floor, its outline laid down toward the lower right (the light on Athas's maps comes from
; the upper left, as the walls' and bones' shadows show), drawn after the floor and before anything else, so
; walls and figures, its own and everyone else's, stand on it.
;
; The game draws a view of the map into a page of its planar (mode X) video memory: first the floor
; (DSUN.EXE 2700Eh: all of the view; 27162h: a rectangle of it), then, row by row, the walls and
; things standing on it and the figures (1DBD:0002). The floor routines are hooked at their start
; (PROBE_FLOOR): their way back is pointed at FLOOR_POST, which draws the shadows over the floor
; they have just drawn, clipped to it, then goes back (not when the routine draws nothing: then
; whatever is there was shadowed already). Each pixel of a shadow is darkened once, by DARK (each
; colour's nearest darker one, at 3/4 strength, among the colours the game doesn't animate). A
; figure's outline is its picture's: the runs of each row of the frame it is drawn with (no colours
; needed), its picture loaded into the cache first if it isn't in memory (as drawing it is about to;
; in a fight most aren't till then).
;
; A figure that moves is drawn again within a rectangle round where it was and where it is; its
; shadow reaches beyond its picture, so the routines redrawing rectangles (PROBE_REDRAW: 2475Fh, a
; rectangle; PROBE_REDRAW_ALL: 24B18h, the one round everything that moved) make theirs bigger by
; as far as a shadow reaches (SHADOW_RIGHT, SHADOW_DOWN), or the old shadow would be left behind.

SHADOW_ROWS  equ 64             ; rows of a figure, up from its feet, that cast a shadow
SHADOW_RIGHT equ 72             ; how far right a shadow reaches past its figure (SHADOW_ROWS * 1.05,
                                ;   and a step of 4: rectangles are kept to whole bytes)
SHADOW_DOWN  equ 44             ; and how far down (SHADOW_ROWS / 2, and a figure's height off the
                                ;   ground)
PAGES_SEG    equ 0x0980         ; (DSUN.EXE segments, less the load segment) the page routines',
                                ;   whose code segment holds the pages' table
CACHE_SEG    equ 0x3E60         ; the picture cache's table: 16 bytes a slot
OBJ_LIST     equ 0x6690         ; DS: far pointer to the things on the map, 8 bytes each (x, y,
OBJ_COUNT    equ 0x1F72         ;   height, flags, which thing), and how many
MAP_THINGS   equ 0x6694         ; DS: each thing on the map, 32 bytes (sprites.py)
MAP_COUNT    equ 520            ; how many things the game has
CACHE_LAST   equ 0x1F84         ; DS: the last slot of the picture cache
FLOOR_ON     equ 0x2F44         ; DS: 0 when the floor routines draw nothing
LOADER_SEG   equ 0x1DF3         ; (DSUN.EXE 25D6Ah) the routine that loads a picture into the cache
LOADER_OFF   equ 0x2A3A         ;   (slot, 0), as drawing one does when it isn't in memory
FIGURE_MOST  equ 128            ; (the widest and tallest a figure's picture may be, for the test of
                                ;   whether its shadow can be where the floor was drawn)

; PROBE_REDRAW: INT VEC_REDRAW replaces "push bp / mov bp,sp / sub sp,8" (6 bytes: INT + 4 NOPs)
; at the start of the routine that draws a rectangle of the view again (camera x, y, page, x0,
; y0, x1, y1, ...): with shadows on, the rectangle reaches further right and down.
probe_redraw:
        push bp
        mov bp, sp
        cmp word [cs:shadows_on], 0
        jne .wide
        cmp word [cs:rings_on], 0
        je .go
.wide:
        add word [bp+22], SHADOW_RIGHT  ; x1 (after BP, the interrupt's IP, CS and flags, and the
        add word [bp+24], SHADOW_DOWN   ;   caller's way back); y1 (the routine keeps both on screen)
.go:    pop bp
        pop word [cs:resume]
        pop word [cs:resume + 2]
        popf
        push bp
        mov bp, sp
        sub sp, 8
        jmp far [cs:resume]

; PROBE_REDRAW_ALL: INT VEC_REDRAW_ALL replaces "push word [bp+8] / push word [bp+6]" (6 bytes:
; INT + 4 NOPs) where the routine drawing again what moved, having made the rectangle round it all
; (x1 at [BP-0Ah], y1 at [BP-0Eh]), starts to draw: with shadows on, it reaches further right and down.
probe_redraw_all:
        pop word [cs:resume]
        pop word [cs:resume + 2]
        pop word [cs:resume_fl]
        cmp word [cs:shadows_on], 0
        jne .wide
        cmp word [cs:rings_on], 0
        je .dust
.wide:  add word [bp-0x0A], SHADOW_RIGHT
        cmp word [bp-0x0A], 0x13F       ; (the routine draws to x1 + 1: kept on screen)
        jle .x
        mov word [bp-0x0A], 0x13F
.x:     add word [bp-0x0E], SHADOW_DOWN
        cmp word [bp-0x0E], 0xC7
        jle .dust
        mov word [bp-0x0E], 0xC7
.dust:  call dust_union
.go:    push word [bp+8]
        push word [bp+6]
        push word [cs:resume_fl]
        push word [cs:resume + 2]
        push word [cs:resume]
        iret

; PROBE_FLOOR: INT VEC_FLOOR_ALL and INT VEC_FLOOR_RECT replace "push bp / mov bp,sp / sub sp,N"
; (6 bytes: INT + 4 NOPs) at the start of the routines drawing the floor of the view (page, camera
; x, y) and of a rectangle of it (page, x0, y0, x1 + 1, y1, camera x, y). With shadows on, their
; way back is FLOOR_POST.
probe_floor_all:
        mov word [cs:floor_frame], 0x1C
        mov byte [cs:floor_kind], 0
        jmp floor_enter
probe_floor_rect:
        mov word [cs:floor_frame], 0x1E
        mov byte [cs:floor_kind], 1
floor_enter:
        pop word [cs:resume]
        pop word [cs:resume + 2]
        popf
        cmp word [cs:shadows_on], 0
        jne .on
        cmp word [cs:dust_on], 0
        jne .on
        cmp word [cs:rings_on], 0
        je .plain
.on:    cmp byte [cs:floor_busy], 0
        jne .plain
        cmp word [FLOOR_ON], 0          ; (DS: the game's) the routine draws nothing without it
        je .plain
        mov byte [cs:floor_busy], 1
        push bp
        mov bp, sp
        push ax
        mov ax, [bp+2]                  ; the caller's way back, kept, and FLOOR_POST in its place
        mov [cs:floor_ret], ax
        mov ax, [bp+4]
        mov [cs:floor_ret + 2], ax
        mov word [bp+2], floor_post
        mov [bp+4], cs
        pop ax
        pop bp
.plain: push bp
        mov bp, sp
        sub sp, [cs:floor_frame]
        jmp far [cs:resume]

; the floor drawn: the shadows on it, then back to the caller (its arguments still on the stack)
floor_post:
        pushf
        pushad
        push ds
        push es
        mov bp, sp
        call shadow_pass
        pop es
        pop ds
        popad
        popf
        mov byte [cs:floor_busy], 0
        jmp far [cs:floor_ret]

F_ARGS equ 38                   ; (FLOOR_POST's frame: ES, DS, PUSHAD, flags, then the arguments)

shadow_pass:
        cld
        inc word [cs:shadow_passes]
        mov [cs:game_ds], ds
        mov ax, ds
        sub ax, DGROUP_SEG
        mov [cs:load_seg], ax
        ; the page: where it is (its bounds, the clip), and the page it is part of (its memory)
        add ax, PAGES_SEG
        mov es, ax
        mov bx, [bp + F_ARGS]
        shl bx, 1
        mov ax, [es:bx + 0x404]
        mov [cs:clip_x0], ax
        mov ax, [es:bx + 0x604]
        mov [cs:clip_y0], ax
        mov ax, [es:bx + 0x804]
        mov [cs:clip_x1], ax
        mov ax, [es:bx + 0xA04]
        mov [cs:clip_y1], ax
.parent:
        test word [es:bx + 0xC04], 0x40
        jz .root
        mov bx, [es:bx + 4]
        jmp .parent
.root:  mov ax, [es:bx + 4]
        mov [cs:v_seg], ax
        mov ax, [es:bx + 0x604]
        mov [cs:v_y0], ax
        mov ax, [es:bx + 0x404]
        shr ax, 2
        mov [cs:v_x0], ax
        mov cx, [es:bx + 0x804]
        shr cx, 2
        sub cx, ax
        inc cx
        mov [cs:v_row], cx
        ; the camera, and for a rectangle's floor the rectangle
        cmp byte [cs:floor_kind], 0
        jne .rect
        mov ax, [bp + F_ARGS + 2]
        mov [cs:cam_x], ax
        mov ax, [bp + F_ARGS + 4]
        mov [cs:cam_y], ax
        jmp .clipped
.rect:  mov ax, [bp + F_ARGS + 10]
        mov [cs:cam_x], ax
        mov ax, [bp + F_ARGS + 12]
        mov [cs:cam_y], ax
        mov ax, [bp + F_ARGS + 2]       ; x0
        cmp ax, [cs:clip_x0]
        jle .rx1
        mov [cs:clip_x0], ax
.rx1:   mov ax, [bp + F_ARGS + 6]       ; x1 + 1
        dec ax
        cmp ax, [cs:clip_x1]
        jge .ry0
        mov [cs:clip_x1], ax
.ry0:   mov ax, [bp + F_ARGS + 4]       ; y0
        cmp ax, [cs:clip_y0]
        jle .ry1
        mov [cs:clip_y0], ax
.ry1:   mov ax, [bp + F_ARGS + 8]       ; y1
        cmp ax, [cs:clip_y1]
        jge .clipped
        mov [cs:clip_y1], ax
.clipped:
        cmp word [cs:dark_build], 0
        je .dark
        call build_dark
        jc .dark                        ; (not yet: the screen is fading)
        mov word [cs:dark_build], 0
.dark:  call vga_save
        cmp word [cs:shadows_on], 0
        je .dust
        cmp byte [cs:dark_ready], 0
        je .dust                        ; (no colours to darken with yet)
        mov ds, [cs:game_ds]
        les di, [OBJ_LIST]
        mov cx, [OBJ_COUNT]
        jcxz .done
.thing: push cx
        push di
        push es
        call shadow_of
        pop es
        pop di
        pop cx
        add di, 8
        loop .thing
.dust:  call ring_pass
        call dust_pass
.done:  call vga_restore
        ret

; the shadow of the thing at ES:DI (DS = the game's), if it casts one
shadow_of:
        mov bx, [es:di + 6]
        cmp bx, MAP_COUNT - 1
        ja .no                          ; (none)
        cmp byte [cs:shadow_tab + bx], 0
        je .no
        shl bx, 5
        add bx, MAP_THINGS
        test byte [bx], 0x80
        jnz .no                         ; (not drawn)
        mov si, [bx + 0x0F]             ; its picture's place in the cache
        cmp si, 0xFFFF
        je .no
        cmp si, [CACHE_LAST]
        ja .no
        ; where its picture is drawn (as the game works it out), on the ground
        mov al, [es:di + 5]
        mov [cs:mirror], al
        xor dx, dx
        test al, 0x20
        jz .fixed
        mov ax, [es:di]
        mov dl, [bx + 7]
        sub ax, dx
        sub ax, [cs:cam_x]
        mov [cs:fig_x], ax
        mov ax, [es:di + 2]
        mov dl, [bx + 8]
        sub ax, dx                      ; (its height off the ground left out: the shadow is on it)
        sub ax, [cs:cam_y]
        mov [cs:fig_y], ax
        jmp .frame
.fixed: mov ax, [bx + 3]
        sub ax, [cs:cam_x]
        mov [cs:fig_x], ax
        mov ax, [bx + 5]
        sub ax, [cs:cam_y]
        mov [cs:fig_y], ax
.frame: mov al, [bx + 0x11]
        xor ah, ah
        mov [cs:frame], ax
        ; (none of its shadow where the floor was drawn: nothing to do)
        mov ax, [cs:fig_x]
        cmp ax, [cs:clip_x1]
        jg .no
        add ax, FIGURE_MOST + SHADOW_RIGHT
        cmp ax, [cs:clip_x0]
        jl .no
        mov ax, [cs:fig_y]
        cmp ax, [cs:clip_y1]
        jg .no
        add ax, FIGURE_MOST + SHADOW_DOWN
        cmp ax, [cs:clip_y0]
        jl .no
        ; its picture, if in the cache
        mov ax, [cs:load_seg]
        add ax, CACHE_SEG
        mov es, ax
        shl si, 4
        cmp dword [es:si + 6], 0
        jl .no
        test byte [es:si + 0x0E], 2
        jnz .loaded
        shr si, 4                       ; (not in memory: loaded, as drawing it is about to)
        push si
        mov ax, [cs:load_seg]
        add ax, LOADER_SEG
        mov [cs:loader + 2], ax
        push word 0
        push si
        call far [cs:loader]
        add sp, 4
        pop si
        or ax, ax
        jz .no
        mov ax, [cs:load_seg]
        add ax, CACHE_SEG
        mov es, ax
        shl si, 4
.loaded:
        les si, [es:si + 0x0A]
        mov bx, [cs:frame]
        cmp bx, [es:si + 4]
        jae .no
        shl bx, 2
        movzx eax, word [cs:zero]       ; (EAX: the frame's address, linear)
        mov ax, es
        shl eax, 4
        movzx ecx, si
        add eax, ecx
        add eax, [es:si + bx + 6]
        mov si, ax
        and si, 0x0F
        shr eax, 4
        mov es, ax
        ; the frame: width, height, then its rows
        mov ax, [es:si]
        mov [cs:f_w], ax
        mov ax, [es:si + 2]
        dec ax
        mov [cs:f_bottom], ax
        add si, 4
.row:   mov al, [es:si]
        inc si
        cmp al, 0xFF
        je .no
        xor ah, ah
        mov [cs:f_y], ax
.run:   mov ax, [es:si]                 ; a run: x (8000h: the row's last), its pixels, its data
        mov [cs:r_x], ax
        mov cl, [es:si + 2]
        mov [cs:r_n], cl
        mov dl, [es:si + 3]
        xor dh, dh
        add si, 4
        add si, dx
        mov ax, [cs:f_bottom]
        sub ax, [cs:f_y]                ; how far up from the feet
        jl .next
        cmp ax, SHADOW_ROWS
        jg .next
        test al, 1
        jnz .next                       ; (every other row: the shadow is half as tall)
        push es
        push si
        call cast_run
        pop si
        pop es
.next:  test byte [cs:r_x + 1], 0x80
        jz .run
        jmp .row
.no:    ret

; the shadow of the current run, AX rows up from the feet
cast_run:
        mov bx, ax
        shr bx, 1
        add bx, [cs:f_bottom]
        add bx, [cs:fig_y]              ; BX: the screen row it falls on
        mov dx, [cs:r_x]
        and dx, 0x7FFF
        xor ch, ch
        mov cl, [cs:r_n]
        test byte [cs:mirror], 0x80
        jz .lean
        mov di, [cs:f_w]                ; (drawn mirrored: from the other side)
        sub di, dx
        sub di, cx
        mov dx, di
.lean:  add dx, [cs:fig_x]
        mov di, ax                      ; leaning right by 1.05 times as far as it is up
        add ax, 10
        push dx
        xor dx, dx
        push bx
        mov bx, 20
        div bx
        pop bx
        pop dx
        add di, ax
        add dx, di                      ; DX: its first x
        mov di, dx
        add di, cx
        dec di                          ; DI: its last
        call darken
        ret

; darken DX..DI on row BX (screen), within the clip
darken: cmp bx, [cs:clip_y0]
        jl .out
        cmp bx, [cs:clip_y1]
        jg .out
        cmp dx, [cs:clip_x0]
        jge .x1
        mov dx, [cs:clip_x0]
.x1:    cmp di, [cs:clip_x1]
        jle .span
        mov di, [cs:clip_x1]
.span:  cmp dx, di
        jg .out
        mov [cs:s_first], dx            ; (before MUL, which takes DX)
        mov [cs:s_last], di
        ; darken DX..DI on row BX, a plane at a time
        mov ax, bx
        sub ax, [cs:v_y0]
        mul word [cs:v_row]
        sub ax, [cs:v_x0]
        mov [cs:row_at], ax
        mov es, [cs:v_seg]
        xor cx, cx                      ; the plane
.plane: mov ax, cx
        sub ax, [cs:s_first]
        and ax, 3
        add ax, [cs:s_first]            ; the first x on this plane
        cmp ax, [cs:s_last]
        jg .nextp
        push ax
        mov dx, 0x3C4                   ; write to this plane, read from it
        mov al, 2
        mov ah, 1
        shl ah, cl
        out dx, ax
        mov dx, 0x3CE
        mov al, 4
        mov ah, cl
        out dx, ax
        pop ax
        mov si, [cs:s_last]
        sub si, ax
        shr si, 2
        inc si                          ; SI: how many
        shr ax, 2
        add ax, [cs:row_at]
        mov di, ax
        xor bh, bh
.pix:   mov bl, [es:di]
        mov bl, [cs:dark + bx]
        mov [es:di], bl
        inc di
        dec si
        jnz .pix
.nextp: inc cx
        cmp cx, 4
        jb .plane
.out:   ret

; the VGA's registers the shadows change, kept and put back
vga_save:
        mov dx, 0x3C4
        in al, dx
        mov [cs:sc_index], al
        mov al, 2
        out dx, al
        inc dx
        in al, dx
        mov [cs:sc_mask], al
        mov dx, 0x3CE
        in al, dx
        mov [cs:gc_index], al
        xor bx, bx
.save:  mov al, [cs:gc_regs + bx]
        out dx, al
        inc dx
        in al, dx
        dec dx
        mov [cs:gc_saved + bx], al
        inc bx
        cmp bx, 5
        jb .save
        mov ax, 0x0001                  ; no set/reset, no rotation, all bits, write mode 0
        out dx, ax
        mov ax, 0x0003
        out dx, ax
        mov ah, [cs:gc_saved + 3]
        and ah, 0xF4
        mov al, 5
        out dx, ax
        mov ax, 0xFF08
        out dx, ax
        ret

vga_restore:
        mov dx, 0x3CE
        xor bx, bx
.put:   mov al, [cs:gc_regs + bx]
        mov ah, [cs:gc_saved + bx]
        out dx, ax
        inc bx
        cmp bx, 5
        jb .put
        mov al, [cs:gc_index]
        out dx, al
        mov dx, 0x3C4
        mov al, 2
        mov ah, [cs:sc_mask]
        out dx, ax
        mov al, [cs:sc_index]
        out dx, al
        ret

; DARK: for each colour of the palette as it is now, the nearest to it at 3/4 strength among the
; colours the game doesn't animate (DARK_FIRST-DARK_LAST: 11-15 and 224-255 cycle, for fire and
; water); made again when the area, so the palette, changes
DARK_FIRST equ 16
DARK_LAST  equ 223
DARK_PARTS equ 3                ; (a shadow's strength: 3/4, as the walls' own shadows on the floor)
DARK_WHOLE equ 4
DARK_HUE   equ 4                ; (how much a change of hue counts against a colour)
DARK_LIT   equ 4000             ; (the palette's 768 values, out of 63 each, add up to less in a fade)
build_dark:
        push ds
        push cs
        pop ds
        mov dx, 0x3C7
        xor al, al
        out dx, al
        mov dx, 0x3C9
        mov di, dac
        mov cx, 768
        xor bx, bx                      ; (BX: how bright it is in all)
.read:  in al, dx
        mov [di], al
        xor ah, ah
        add bx, ax
        inc di
        loop .read
        cmp bx, DARK_LIT
        jae .lit
        pop ds                          ; (nearly black: a fade, not the area's colours)
        stc
        ret
.lit:
        xor bx, bx                      ; the colour
.colour:
        mov si, bx
        imul si, si, 3
        add si, dac
        xor di, di                      ; its darker self
.chan:  lodsb
        mov ah, DARK_PARTS
        mul ah
        mov dl, DARK_WHOLE
        div dl
        mov [want + di], al
        inc di
        cmp di, 3
        jb .chan
        mov si, bx                      ; (only clearly darker ones: brightness under 7/8 of its own)
        imul si, si, 3
        add si, dac
        xor ax, ax
        xor dx, dx
        mov di, 3
.own:   lodsb
        add dx, ax
        dec di
        jnz .own
        imul dx, dx, 7
        shr dx, 3
        mov [lit_most], dx
        mov dword [best_d], 0xFFFFFFFF
        mov [best_c], bl
        mov cx, DARK_FIRST
.cand:  mov word [lit_sum], 0
        mov si, cx                      ; how far a colour is from the one wanted: the differences
        imul si, si, 3                  ;   squared, and those between them weighted (DARK_HUE),
        add si, dac                     ;   so that it keeps its hue (sand stays sand, not pink)
        xor di, di
.diff:  lodsb
        mov ah, 0
        add [lit_sum], ax
        sub al, [want + di]
        cbw
        mov [diffs + di], al
        inc di
        cmp di, 3
        jb .diff
        mov ax, [lit_sum]
        cmp ax, [lit_most]
        jae .worse                      ; (not darker enough)
        xor edx, edx
        xor di, di
.sq:    movsx eax, byte [diffs + di]
        imul eax, eax
        add edx, eax
        inc di
        cmp di, 3
        jb .sq
        movsx eax, byte [diffs]
        movsx edi, byte [diffs + 1]
        sub eax, edi
        imul eax, eax
        imul eax, eax, DARK_HUE
        add edx, eax
        movsx eax, byte [diffs + 1]
        movsx edi, byte [diffs + 2]
        sub eax, edi
        imul eax, eax
        imul eax, eax, DARK_HUE
        add edx, eax
        cmp edx, [best_d]
        jae .worse
        mov [best_d], edx
        mov [best_c], cl
.worse: inc cx
        cmp cx, DARK_LAST
        jbe .cand
        mov al, [best_c]
        mov [dark + bx], al
        inc bx
        cmp bx, 256
        jb .colour
        mov byte [dark_ready], 1
        pop ds
        clc
        ret

; SCROLLING (SCROLL_ON): holding the right mouse button and moving scrolls the map with the pointer,
; as if dragging it; a right click (released before the pointer has moved DRAG_START pixels) is
; still the game's (it changes what the pointer does: walk, use, look).
;
; The game is told of the mouse's buttons by the mouse driver calling its handler (INT 33h, 0Ch).
; INT33 puts MOUSE_EVENT in its place, which keeps the right button from the game while it is
; held: if it was a click, the game gets the press and the release when it is let go; if it was a
; drag, nothing. The game's main loop reads where the pointer is (DSUN.EXE 1CAACh, the call to the
; driver's 03h), to scroll the map when it is at the screen's edge; PROBE_SCROLL makes that call
; itself and, while dragging, has the game centre its view where the drag puts it (191F:0281h, as
; clicking on the overview map does: the view is then drawn again), and the pointer is kept off
; the edges. It also scrolls by what the companion adds to PAN_X and PAN_Y.

DRAG_START  equ 4               ; pixels the pointer moves before a right click is a drag
CAM_X       equ 0x1178          ; DS: the view's top left on the map
CAM_Y       equ 0x117A
CAM_X_MOST  equ 0x6C0           ; (as far as the game lets it go: the map less the view)
CAM_Y_MOST  equ 0x558
CENTRE_SEG  equ 0x191F          ; (DSUN.EXE 1E871h) centre the view on (x, y, 1: draw it again)
CENTRE_OFF  equ 0x0281
EVENT_PRESS equ 8               ; the driver's events: right button pressed, released
EVENT_LEAVE equ 16
RIGHT       equ 2               ; the right button, in the buttons held
MIDDLE      equ 4               ; the middle one (pressing the wheel)
EVENT_MID_PRESS equ 0x20
EVENT_MID_LEAVE equ 0x40
SCROLL_MIDDLE equ 1             ; SCROLL_ON's bits: dragging with the wheel pressed,
SCROLL_RIGHT  equ 2             ;   with the right button held

int33:
        cmp ax, 0x0C
        jne .chain
        or cx, cx
        jz .chain                       ; (taking the handler away)
        mov [cs:game_handler], dx
        mov [cs:game_handler + 2], es
        mov [cs:game_mask], cx
        push es
        push dx
        push cx
        or cx, 0x7F                     ; (moves, and all three buttons)
        push cs
        pop es
        mov dx, mouse_event
        pushf
        call far [cs:old33]
        pop cx
        pop dx
        pop es
        iret
.chain: jmp far [cs:old33]

mouse_event:                            ; AX = events, BX = buttons held, CX, DX = where
        cmp word [cs:scroll_on], 0
        je .pass
        test byte [cs:scroll_on], SCROLL_MIDDLE
        jz .right
        test al, EVENT_MID_PRESS        ; the wheel pressed: a drag at once (the game has no use
        jz .mheld                       ;   for that button)
        cmp byte [cs:drag], 0
        jne .mheld
        mov byte [cs:drag], 2
        mov byte [cs:drag_mid], 1
        mov byte [cs:drag_new], 1
        mov [cs:drag_x], cx
        mov [cs:drag_y], dx
.mheld: cmp byte [cs:drag_mid], 0
        je .right
        and bx, ~MIDDLE
        test al, EVENT_MID_LEAVE
        jz .mdone
        mov byte [cs:drag], 0
        mov byte [cs:drag_mid], 0
.mdone: and al, ~(EVENT_MID_PRESS | EVENT_MID_LEAVE)
        jmp .pass
.right: test byte [cs:scroll_on], SCROLL_RIGHT
        jz .pass
        test al, EVENT_PRESS
        jz .held
        cmp byte [cs:drag], 0
        jne .held
        mov byte [cs:drag], 1
        mov [cs:drag_x], cx
        mov [cs:drag_y], dx
        and al, ~EVENT_PRESS
.held:  cmp byte [cs:drag], 0
        je .pass
        and bx, ~RIGHT
        cmp byte [cs:drag], 1
        jne .leave
        push ax                         ; moved far enough to be a drag?
        mov ax, cx
        sub ax, [cs:drag_x]
        call .apart
        jnc .y
        mov ax, dx
        sub ax, [cs:drag_y]
        call .apart
        jc .near
.y:     mov byte [cs:drag], 2
        mov byte [cs:drag_new], 1
.near:  pop ax
.leave: test al, EVENT_LEAVE
        jz .pass
        and al, ~EVENT_LEAVE
        cmp byte [cs:drag], 1
        mov byte [cs:drag], 0
        jne .pass                       ; (a drag: the game never knows)
        pusha                           ; a click: pressed and released, where it was pressed
        or bx, RIGHT
        mov cx, [cs:drag_x]
        mov dx, [cs:drag_y]
        mov ax, EVENT_PRESS
        call .give
        popa
        pusha
        mov ax, EVENT_LEAVE
        call .give
        popa
.pass:  call .give
        retf
.give:  and ax, [cs:game_mask]          ; the events the game asked for, to its handler
        jz .none
        pusha
        push ds
        push es
        call far [cs:game_handler]
        pop es
        pop ds
        popa
.none:  ret
.apart: or ax, ax                       ; CF clear when |AX| >= DRAG_START
        jns .pos
        neg ax
.pos:   cmp ax, DRAG_START
        ret

; PROBE_SCROLL: INT VEC_SCROLL replaces the start of "call far 3118:002E" (9Ah 2Eh 00h, then the
; segment: A9h makes it a harmless "test ax,<segment>" the loader may relocate), the game's main
; loop asking where the pointer is (its arguments, far pointers to x and y, on the stack).
probe_scroll:
        pop word [cs:s_resume]
        pop word [cs:s_resume + 2]
        pop word [cs:s_resume_fl]
        add word [cs:s_resume], 3       ; (past the segment)
        push bp
        mov bp, sp
        push es
        push bx
        push cx
        push dx
        push si
        push di
        inc word [cs:main_ticks]
        call dust_tick
        call target_click
        cmp word [cs:view_redraw], 0
        je .read
        mov word [cs:view_redraw], 0
        call view_again
.read:  mov ax, 3
        int 0x33                        ; BX = buttons, CX, DX = where
        cmp word [cs:scroll_on], 0
        je .wheel                       ; (the companion's scrolling, as for a chosen enemy, anyway)
        cmp byte [cs:drag], 2
        jne .wheel
        cmp byte [cs:drag_new], 0
        je .follow
        mov byte [cs:drag_new], 0
        mov ax, [CAM_X]
        mov [cs:cam0_x], ax
        mov ax, [CAM_Y]
        mov [cs:cam0_y], ax
.follow:
        mov ax, [cs:cam0_x]             ; where the drag puts the view: the map moves with it
        sub ax, cx
        add ax, [cs:drag_x]
        mov si, [cs:cam0_y]
        sub si, dx
        add si, [cs:drag_y]
        call pan_to
.wheel: mov ax, [cs:pan_x]              ; the companion's
        sub ax, [cs:pan_x_done]
        mov si, [cs:pan_y]
        sub si, [cs:pan_y_done]
        mov di, ax
        or di, si
        jz .report
        add [cs:pan_x_done], ax
        add [cs:pan_y_done], si
        add [cs:cam0_x], ax             ; (a drag under way goes on from there)
        add [cs:cam0_y], si
        add ax, [CAM_X]
        add si, [CAM_Y]
        call pan_to
.report:
        cmp byte [cs:drag], 0
        je .put
        and bx, ~(RIGHT | MIDDLE)
        cmp cx, 1                       ; (off the edges: no scrolling of the game's own)
        jge .x1
        mov cx, 1
.x1:    cmp cx, 0x13D
        jle .y0
        mov cx, 0x13D
.y0:    cmp dx, 1
        jge .y1
        mov dx, 1
.y1:    cmp dx, 0xC6
        jle .put
        mov dx, 0xC6
.put:   les di, [bp + 2]
        mov [es:di], cx
        les di, [bp + 6]
        mov [es:di], dx
        mov ax, bx
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        pop es
        pop bp
        push word [cs:s_resume_fl]
        push word [cs:s_resume + 2]
        push word [cs:s_resume]
        iret

pan_to:                                 ; the view's top left to (AX, SI) as far as the map goes;
        cmp ax, 0                       ;   keeps CX, DX
        jge .x1
        xor ax, ax
.x1:    cmp ax, CAM_X_MOST
        jle .y0
        mov ax, CAM_X_MOST
.y0:    cmp si, 0
        jge .y1
        xor si, si
.y1:    cmp si, CAM_Y_MOST
        jle .snap
        mov si, CAM_Y_MOST
.snap:  and ax, 0xFFF8                  ; (as the game keeps it)
        and si, 0xFFF8
        cmp ax, [CAM_X]
        jne .go
        cmp si, [CAM_Y]
        je .done
.go:    call centre_on
.done:  ret

centre_on:                              ; the view's top left to (AX, SI), drawn again; keeps CX, DX
        push cx
        push dx
        push bx
        mov bx, ds
        sub bx, DGROUP_SEG - CENTRE_SEG
        mov [cs:centre + 2], bx
        push 1
        add si, 100
        push si
        add ax, 160
        push ax
        call far [cs:centre]
        add sp, 6
        pop bx
        pop dx
        pop cx
        ret

; DUST (DUST_ON): a figure walking raises puffs of dust behind it, which spread, rise a little and
; fade away in about a second (DUST_LIFE ticks of the BIOS clock). Each is drawn on the floor as the
; shadows are (DUST_PASS: before the walls and figures, which stand in it), lightening the ground's
; colours through LIGHT (made by the companion from the palette: 0 for colours that aren't ground
; dust shows on, so only sand and dirt take it), dithered thinner toward its edge and as it fades,
; by a pattern fixed to the map (so a puff looks the same however much of it is drawn again).
;
; DUST_TICK, from the main loop (PROBE_SCROLL), notes how far each figure that casts a shadow
; (SHADOW_TAB) has walked, and raises a puff behind its feet every DUST_STEP pixels. While puffs
; change (each tick of the clock), their ground is to be drawn again: the rectangle the game draws
; again round what moved takes them in (DUST_UNION, from PROBE_REDRAW_ALL), and when no one is
; walking, DUST_NUDGE has the game draw the view again. Nothing of the game's is changed (marking a
; figure changed to have it drawn again can set one in a fight walking again).

DUST_LIFE  equ 18               ; ticks of the BIOS clock (18.2 a second) a puff lasts
DUST_STEP  equ 6                ; pixels walked for each puff
JUMP_MOST  equ 40               ; a move further than this (across or up and down) is a jump, not a walk
PUFFS      equ 24               ; puffs at most at once
PUFF_SIZE  equ 12               ; a puff: x, y (on the map), born (ticks), owner (thing), seed, live
BIOS_TICKS equ 0x46C

dust_tick:                      ; DS = the game's
        cmp word [cs:dust_on], 0
        jne .on
        ret
.on:    push es
        push bp
        xor ax, ax
        mov es, ax
        mov ax, [es:BIOS_TICKS]
        mov [cs:d_now], ax
        cmp ax, [cs:d_last]
        je .walk
        mov [cs:d_last], ax
        mov si, puffs                   ; a tick on: each puff looks different, or is gone
        mov cx, PUFFS
.age:   cmp byte [cs:si + 10], 0
        je .anext
        call puff_dirty
        mov ax, [cs:d_now]
        sub ax, [cs:si + 4]
        cmp ax, DUST_LIFE
        jbe .anext
        mov byte [cs:si + 10], 0        ; (drawn once more, gone: now free)
.anext: add si, PUFF_SIZE
        loop .age
.walk:  les di, [OBJ_LIST]
        mov cx, [OBJ_COUNT]
        or cx, cx
        jz .done
.thing: push cx
        mov bx, [es:di + 6]
        cmp bx, MAP_COUNT - 1
        ja .tnext
        cmp byte [cs:shadow_tab + bx], 0
        je .tnext
        mov [cs:t_thing], bx
        mov ax, [es:di]
        mov [cs:t_x], ax
        mov dx, [es:di + 2]
        mov [cs:t_y], dx
        shl bx, 1
        sub ax, [cs:last_x + bx]
        mov [cs:t_dx], ax
        sub dx, [cs:last_y + bx]
        mov [cs:t_dy], dx
        mov ax, [cs:t_x]
        mov [cs:last_x + bx], ax
        mov ax, [cs:t_y]
        mov [cs:last_y + bx], ax
        mov ax, [cs:t_dx]               ; walked a little (not a jump: an area loaded, someone placed)
        call abs16
        cmp ax, JUMP_MOST
        jae .tnext
        mov cx, ax
        mov ax, [cs:t_dy]
        call abs16
        cmp ax, JUMP_MOST
        jae .tnext
        add ax, cx
        jz .tnext
        mov ax, [cs:d_now]
        mov [cs:d_walked_at], ax
        mov bx, [cs:t_thing]
        add [cs:walked + bx], al
        cmp byte [cs:walked + bx], DUST_STEP
        jb .tnext
        sub byte [cs:walked + bx], DUST_STEP
        cmp byte [cs:walked + bx], DUST_STEP
        jb .one
        mov byte [cs:walked + bx], 0        ; (one puff a tick at most)
.one:
        call puff_raise
.tnext: pop cx
        add di, 8
        dec cx
        jnz .thing
.done:  call dust_nudge
        pop bp
        pop es
        ret

abs16:  or ax, ax
        jns .pos
        neg ax
.pos:   ret

sgn16:  or ax, ax                       ; AX -> -1, 0 or 1
        jz .z
        mov ax, 1
        jg .z
        neg ax
.z:     ret

puff_raise:                             ; behind T_THING's feet at (T_X, T_Y), walking (T_DX, T_DY)
        mov ax, [cs:d_next]             ; the next in turn (the oldest, if all are in use)
        inc word [cs:d_next]
        cmp word [cs:d_next], PUFFS
        jb .slot
        mov word [cs:d_next], 0
.slot:  imul si, ax, PUFF_SIZE
        add si, puffs
        cmp byte [cs:si + 10], 0
        je .free
        call puff_dirty                 ; (its ground drawn again without it)
.free:  xor byte [cs:d_side], 1         ; (the feet in turn: a little to one side, then the other)
        mov ax, [cs:t_dx]
        call sgn16
        mov [cs:t_sx], ax
        mov ax, [cs:t_dy]
        call sgn16
        mov [cs:t_sy], ax
        mov ax, [cs:t_sx]               ; x: behind, and to the side across the way it goes
        imul ax, ax, -3
        add ax, [cs:t_x]
        mov dx, [cs:t_sy]
        shl dx, 1
        cmp byte [cs:d_side], 0
        je .x
        neg dx
.x:     add ax, dx
        mov [cs:si], ax
        mov ax, [cs:t_sy]               ; y: behind, and to the side
        imul ax, ax, -2
        add ax, [cs:t_y]
        mov dx, [cs:t_sx]
        cmp byte [cs:d_side], 0
        jne .y
        neg dx
.y:     add ax, dx
        mov [cs:si + 2], ax
        mov ax, [cs:d_now]
        mov [cs:si + 4], ax
        mov ax, [cs:t_thing]
        mov [cs:si + 6], ax
        inc word [cs:dust_puffs]
        imul ax, [cs:dust_puffs], 0x3D7
        mov [cs:si + 8], ax
        mov byte [cs:si + 10], 1
        call puff_dirty
        ret

puff_dirty:                             ; the puff at CS:SI: its ground to be drawn again (DS = the game's)
        mov ax, [cs:si]
        sub ax, 12
        mov dx, [cs:si + 2]
        sub dx, 12
        cmp byte [cs:d_dirty], 0
        je .first
        cmp ax, [cs:d_x0]
        jge .x1
.first: mov [cs:d_x0], ax
.x1:    add ax, 24
        cmp byte [cs:d_dirty], 0
        je .fx1
        cmp ax, [cs:d_x1]
        jle .y0
.fx1:   mov [cs:d_x1], ax
.y0:    cmp byte [cs:d_dirty], 0
        je .fy0
        cmp dx, [cs:d_y0]
        jge .y1
.fy0:   mov [cs:d_y0], dx
.y1:    add dx, 19
        cmp byte [cs:d_dirty], 0
        je .fy1
        cmp dx, [cs:d_y1]
        jle .mark
.fy1:   mov [cs:d_y1], dx
.mark:  mov byte [cs:d_dirty], 1
        mov ax, [cs:si + 6]
        mov [cs:d_owner], ax
        ret

STILL_TICKS equ 3              ; how long no one has walked (nor the view moved) before DUST_NUDGE
NUDGE_TICKS equ 4               ; ... and between its drawings of the view

; DUST_NUDGE: with puffs to draw again while no one walks and the view stands still (when the
; game draws again round what moved anyway, DUST_UNION taking them in), the view drawn again
; (VIEW_AGAIN) every NUDGE_TICKS, till they are gone
dust_nudge:
        mov ax, [CAM_X]                 ; (the view: when it last moved)
        cmp ax, [cs:d_cam_x]
        jne .cam
        mov ax, [CAM_Y]
        cmp ax, [cs:d_cam_y]
        je .still
.cam:   mov ax, [CAM_X]
        mov [cs:d_cam_x], ax
        mov ax, [CAM_Y]
        mov [cs:d_cam_y], ax
        mov ax, [cs:d_now]
        mov [cs:d_walked_at], ax
        ret
.still: cmp byte [cs:d_dirty], 0
        je .ret
        mov ax, [cs:d_now]
        sub ax, [cs:d_walked_at]
        cmp ax, STILL_TICKS
        jb .ret
        mov ax, [cs:d_now]
        sub ax, [cs:d_nudged]
        cmp ax, NUDGE_TICKS
        jb .ret
        mov ax, [cs:d_now]
        mov [cs:d_nudged], ax
        mov byte [cs:d_dirty], 0
        call view_again
.ret:   ret

; VIEW_AGAIN: the view drawn again, all of it, as the game does when the view is centred where it
; is (DS = the game's). The figures are never marked changed to have them drawn again: in a fight
; that can set one walking again.
view_again:
        push ax
        push bx
        push cx
        push dx
        push si
        mov si, [CAM_Y]
        mov ax, [CAM_X]
        call centre_on
        pop si
        pop dx
        pop cx
        pop bx
        pop ax
        ret

; DUST_UNION: in PROBE_REDRAW_ALL (x0 [BP-8], x1 [BP-0Ah], y0 [BP-0Ch], y1 [BP-0Eh]: on screen),
; the puffs' ground taken in, as far as it is on screen
dust_union:
        cmp byte [cs:d_dirty], 0
        je .ret
        mov byte [cs:d_dirty], 0
        mov ax, [cs:d_x0]
        sub ax, [CAM_X]
        mov cx, [cs:d_x1]
        sub cx, [CAM_X]
        mov dx, [cs:d_y0]
        sub dx, [CAM_Y]
        mov bx, [cs:d_y1]
        sub bx, [CAM_Y]
        cmp cx, 0                       ; (off screen: nothing)
        jl .ret
        cmp ax, 0x13F
        jg .ret
        cmp bx, 0
        jl .ret
        cmp dx, 0xC7
        jg .ret
        cmp ax, 0
        jge .ax
        xor ax, ax
.ax:    and ax, 0xFFFC
        cmp ax, [bp-8]
        jge .cx
        mov [bp-8], ax
.cx:    cmp cx, 0x13F
        jle .cx3
        mov cx, 0x13F
.cx3:   or cx, 3
        cmp cx, [bp-0x0A]
        jle .dx
        mov [bp-0x0A], cx
.dx:    cmp dx, 0
        jge .dx0
        xor dx, dx
.dx0:   cmp dx, [bp-0x0C]
        jge .bx
        mov [bp-0x0C], dx
.bx:    cmp bx, 0xC7
        jle .bx1
        mov bx, 0xC7
.bx1:   cmp bx, [bp-0x0E]
        jle .ret
        mov [bp-0x0E], bx
.ret:   ret

; DUST_PASS: in SHADOW_PASS (the VGA's registers kept; the clip, camera and page known), each puff
dust_pass:
        cmp word [cs:dust_on], 0
        je .ret
        push ds
        xor ax, ax
        mov ds, ax
        mov ax, [BIOS_TICKS]
        pop ds
        mov [cs:d_now], ax
        mov si, puffs
        mov cx, PUFFS
.puff:  cmp byte [cs:si + 10], 0
        je .next
        push cx
        push si
        call puff_draw
        pop si
        pop cx
.next:  add si, PUFF_SIZE
        loop .puff
.ret:   ret

puff_draw:                              ; the puff at CS:SI
        mov ax, [cs:d_now]
        sub ax, [cs:si + 4]
        cmp ax, DUST_LIFE
        jb .young
        ret
.young: mov bx, ax                      ; BX: its age
        shl ax, 3                       ; across: 3, growing to 11
        xor dx, dx
        mov cx, DUST_LIFE
        div cx
        add ax, 3
        mov [cs:d_rx], ax
        imul ax, ax, 9                  ; up and down: a little over half that
        add ax, 8
        shr ax, 4
        mov [cs:d_ry], ax
        mov al, [cs:dust_dens + bx]
        xor ah, ah
        mov [cs:d_dens], ax
        mov al, [cs:dust_core + bx]
        mov [cs:d_core], ax
        imul ax, bx, 5                  ; rising, 5 pixels in all
        xor dx, dx
        div cx
        mov dx, [cs:si + 2]
        sub dx, ax
        mov [cs:d_wy], dx
        mov ax, [cs:si]
        mov [cs:d_wx], ax
        mov ax, [cs:si + 8]
        mov [cs:d_seed], ax
        mov ax, [cs:d_ry]
        neg ax
        mov [cs:d_yy], ax
.row:   mov ax, [cs:d_yy]
        cmp ax, [cs:d_ry]
        jle .inrow
        ret
.inrow: mov bx, [cs:d_wy]
        add bx, ax
        mov [cs:d_wrow], bx
        sub bx, [cs:cam_y]
        cmp bx, [cs:clip_y0]
        jl .nrow
        cmp bx, [cs:clip_y1]
        jg .nrow
        mov ax, bx                      ; the row's place in the page
        sub ax, [cs:v_y0]
        mul word [cs:v_row]
        sub ax, [cs:v_x0]
        mov [cs:row_at], ax
        mov ax, [cs:d_yy]               ; how far out it is, up and down: (y / ry)^2, of 256
        imul ax, ax
        shl ax, 8
        mov cx, [cs:d_ry]
        imul cx, cx
        xor dx, dx
        div cx
        mov [cs:d_ey], ax
        mov ax, [cs:d_rx]
        neg ax
        mov [cs:d_xx], ax
.col:   mov ax, [cs:d_xx]
        cmp ax, [cs:d_rx]
        jg .nrow
        imul ax, ax                     ; and across
        shl ax, 8
        mov cx, [cs:d_rx]
        imul cx, cx
        xor dx, dx
        div cx
        add ax, [cs:d_ey]
        cmp ax, 256
        ja .ncol
        mov [cs:d_e], ax
        mov bx, [cs:d_wx]
        add bx, [cs:d_xx]
        mov [cs:d_wcol], bx
        sub bx, [cs:cam_x]
        cmp bx, [cs:clip_x0]
        jl .ncol
        cmp bx, [cs:clip_x1]
        jg .ncol
        mov ax, [cs:d_e]                ; how thick it is here: thinner toward the edge
        imul ax, ax, 154
        shr ax, 8
        neg ax
        add ax, 256
        mul word [cs:d_dens]
        shr ax, 8
        mov [cs:d_thr], ax
        mov ax, [cs:d_wcol]             ; the pattern, fixed to the map
        imul ax, ax, 0x9E5
        mov dx, [cs:d_wrow]
        imul dx, dx, 0x3B1
        xor ax, dx
        add ax, [cs:d_seed]
        mov dx, ax
        shr dx, 7
        xor ax, dx
        imul ax, ax, 0x2C5
        shr ax, 4
        and ax, 0xFF
        cmp ax, [cs:d_thr]
        jae .ncol
        call dust_px
.ncol:  inc word [cs:d_xx]
        jmp .col
.nrow:  inc word [cs:d_yy]
        jmp .row

dust_px:                                ; lighten screen x BX on the row at ROW_AT (twice in the core)
        mov cx, bx
        and cx, 3
        mov dx, 0x3C4
        mov al, 2
        mov ah, 1
        shl ah, cl
        out dx, ax
        mov dx, 0x3CE
        mov al, 4
        mov ah, cl
        out dx, ax
        shr bx, 2
        add bx, [cs:row_at]
        mov es, [cs:v_seg]
        xor ax, ax
        mov al, [es:bx]
        mov di, ax
        mov al, [cs:light + di]
        or al, al
        jz .ret
        mov cx, [cs:d_e]
        cmp cx, [cs:d_core]
        jae .put
        mov di, ax
        mov ah, [cs:light + di]
        or ah, ah
        jz .put
        mov al, ah
.put:   mov [es:bx], al
.ret:   ret

dust_dens  db 255, 255, 255, 255, 247, 238, 229, 219, 209, 198, 187, 174, 161, 147, 132, 114, 93, 66   ; how thick, by age (of 256)
dust_core  db 140, 132, 125, 117, 109, 101, 93, 86, 78, 70, 62, 54, 46, 39, 31, 23, 15, 7   ; the core (twice as light), by age
d_now      dw 0
d_nudged   dw 0
d_cam_x    dw 0
d_cam_y    dw 0
d_owner    dw 0
d_walked_at dw 0                ; when someone last took a step
d_last     dw 0
d_next     dw 0
d_side     db 0
d_dirty    db 0
d_x0       dw 0
d_x1       dw 0
d_y0       dw 0
d_y1       dw 0
d_rx       dw 0
d_ry       dw 0
d_dens     dw 0
d_core     dw 0
d_wx       dw 0
d_wy       dw 0
d_seed     dw 0
d_yy       dw 0
d_xx       dw 0
d_wrow     dw 0
d_wcol     dw 0
d_ey       dw 0
d_e        dw 0
d_thr      dw 0
t_thing    dw 0
t_x        dw 0
t_y        dw 0
t_dx       dw 0
t_dy       dw 0
t_sx       dw 0
t_sy       dw 0
puffs      times PUFFS * PUFF_SIZE db 0
last_x     times MAP_COUNT dw 0
last_y     times MAP_COUNT dw 0
walked     times MAP_COUNT db 0
light      times 256 db 0

; RINGS (RINGS_ON): a ring on the ground under each thing RING_TAB marks (the companion marks the
; enemies in a fight, and the one chosen with Tab), drawn in the floor pass as the shadows are, so
; the figures stand in it, the ground's colours reddened through RED (made by the companion from the
; palette): two pixels thick, the chosen one's three, and redder.
ring_pass:
        cmp word [cs:rings_on], 0
        je .ret
        mov ds, [cs:game_ds]
        les di, [OBJ_LIST]
        mov cx, [OBJ_COUNT]
        or cx, cx
        jz .ret
.thing: push cx
        push di
        push es
        mov bx, [es:di + 6]
        cmp bx, MAP_COUNT - 1
        ja .next
        mov al, [cs:ring_tab + bx]
        or al, al
        jz .next
        mov [cs:r_kind], al
        mov ax, [es:di]
        sub ax, [cs:cam_x]
        mov [cs:r_fx], ax
        mov ax, [es:di + 2]
        sub ax, [cs:cam_y]
        mov [cs:r_fy], ax
        mov si, ring_outer
        mov cx, RING_OUTER
        call ring_points
        mov si, ring_inner
        mov cx, RING_INNER
        call ring_points
        cmp byte [cs:r_kind], 2
        jne .next
        mov si, ring_extra
        mov cx, RING_EXTRA
        call ring_points
.next:  pop es
        pop di
        pop cx
        add di, 8
        loop .thing
.ret:   ret

ring_points:                            ; CX points (dx, dy bytes) at CS:SI, round (R_FX, R_FY)
.pt:    push cx
        mov al, [cs:si]
        cbw
        add ax, [cs:r_fx]
        mov bx, ax
        mov al, [cs:si + 1]
        cbw
        add ax, [cs:r_fy]
        add si, 2
        cmp ax, [cs:clip_y0]
        jl .skip
        cmp ax, [cs:clip_y1]
        jg .skip
        cmp bx, [cs:clip_x0]
        jl .skip
        cmp bx, [cs:clip_x1]
        jg .skip
        sub ax, [cs:v_y0]               ; the row's place in the page
        mul word [cs:v_row]
        sub ax, [cs:v_x0]
        mov [cs:row_at], ax
        push si
        call ring_px
        pop si
.skip:  pop cx
        loop .pt
        ret

ring_px:                                ; redden screen x BX on the row at ROW_AT (twice for the chosen)
        mov cx, bx
        and cx, 3
        mov dx, 0x3C4
        mov al, 2
        mov ah, 1
        shl ah, cl
        out dx, ax
        mov dx, 0x3CE
        mov al, 4
        mov ah, cl
        out dx, ax
        shr bx, 2
        add bx, [cs:row_at]
        mov es, [cs:v_seg]
        xor ax, ax
        mov al, [es:bx]
        mov cl, [cs:r_kind]
        inc cl                          ; (reddened twice, the chosen one three times)
.again: mov di, ax
        mov ah, [cs:red + di]
        or ah, ah
        jz .put
        mov al, ah
        xor ah, ah
        dec cl
        jnz .again
.put:   mov [es:bx], al
        ret

RING_OUTER equ 76
RING_INNER equ 68
RING_EXTRA equ 84
ring_outer db 13, 0, 13, 1, 13, 2, 12, 2, 12, 3, 11, 3, 11, 4, 10, 4, 9, 4, 9, 5, 8, 5, 7, 5, 6, 5, 5, 5, 5, 6, 4, 6, 3, 6, 2, 6, 1, 6, 0, 6, 255, 6, 254, 6, 253, 6, 252, 6, 251, 6, 251, 5, 250, 5, 249, 5, 248, 5, 247, 5, 247, 4, 246, 4, 245, 4, 245, 3, 244, 3, 244, 2, 243, 2, 243, 1, 243, 0, 243, 255, 243, 254, 244, 254, 244, 253, 245, 253, 245, 252, 246, 252, 247, 252, 247, 251, 248, 251, 249, 251, 250, 251, 251, 251, 251, 250, 252, 250, 253, 250, 254, 250, 255, 250, 0, 250, 1, 250, 2, 250, 3, 250, 4, 250, 5, 250, 5, 251, 6, 251, 7, 251, 8, 251, 9, 251, 9, 252, 10, 252, 11, 252, 11, 253, 12, 253, 12, 254, 13, 254, 13, 255
ring_inner db 12, 0, 12, 1, 11, 1, 11, 2, 10, 2, 10, 3, 9, 3, 9, 4, 8, 4, 7, 4, 6, 4, 5, 4, 5, 5, 4, 5, 3, 5, 2, 5, 1, 5, 0, 5, 255, 5, 254, 5, 253, 5, 252, 5, 251, 5, 251, 4, 250, 4, 249, 4, 248, 4, 247, 4, 247, 3, 246, 3, 246, 2, 245, 2, 245, 1, 244, 1, 244, 0, 244, 255, 245, 255, 245, 254, 246, 254, 246, 253, 247, 253, 247, 252, 248, 252, 249, 252, 250, 252, 251, 252, 251, 251, 252, 251, 253, 251, 254, 251, 255, 251, 0, 251, 1, 251, 2, 251, 3, 251, 4, 251, 5, 251, 5, 252, 6, 252, 7, 252, 8, 252, 9, 252, 9, 253, 10, 253, 10, 254, 11, 254, 11, 255, 12, 255
ring_extra db 14, 0, 14, 1, 14, 2, 13, 2, 13, 3, 12, 3, 12, 4, 11, 4, 11, 5, 10, 5, 9, 5, 9, 6, 8, 6, 7, 6, 6, 6, 5, 6, 5, 7, 4, 7, 3, 7, 2, 7, 1, 7, 0, 7, 255, 7, 254, 7, 253, 7, 252, 7, 251, 7, 251, 6, 250, 6, 249, 6, 248, 6, 247, 6, 247, 5, 246, 5, 245, 5, 245, 4, 244, 4, 244, 3, 243, 3, 243, 2, 242, 2, 242, 1, 242, 0, 242, 255, 242, 254, 243, 254, 243, 253, 244, 253, 244, 252, 245, 252, 245, 251, 246, 251, 247, 251, 247, 250, 248, 250, 249, 250, 250, 250, 251, 250, 251, 249, 252, 249, 253, 249, 254, 249, 255, 249, 0, 249, 1, 249, 2, 249, 3, 249, 4, 249, 5, 249, 5, 250, 6, 250, 7, 250, 8, 250, 9, 250, 9, 251, 10, 251, 11, 251, 11, 252, 12, 252, 12, 253, 13, 253, 13, 254, 14, 254, 14, 255
r_kind     db 0
r_fx       dw 0
r_fy       dw 0
ring_tab   times MAP_COUNT db 0
red        times 256 db 0

; TARGETING (TARGET_ON): Tab and Shift+Tab, counted for the companion, choose an enemy in a fight
; (its ring brighter: RINGS); Enter attacks it, as a click on it does, even where another figure
; stands in front of it. The game reads keys through INT 16h: INT16 takes Tab, Shift+Tab and (with
; an enemy chosen) Enter out of what it sees. For Enter, the main loop (TARGET_CLICK, from
; PROBE_SCROLL) puts the pointer at the enemy's feet and gives the game a left click there, while
; the routine that finds what is under the pointer (PROBE_HIT, DSUN.EXE 25B52h) answers with the
; chosen enemy for a moment (HIT_PASSES), whatever is in front of it.

KEY_TAB     equ 0x0F09
KEY_BACKTAB equ 0x0F00
KEY_ENTER   equ 0x1C0D
KEY_PAD_ENTER equ 0xE00D
HIT_PASSES  equ 600             ; passes of the map's main loop the hit is the chosen enemy, from the
                                ;   click (not BIOS ticks: the BIOS clock can stand still in a fight,
                                ;   and the hit stayed the enemy, the walk to it stalling)
EVENT_LEFT_PRESS equ 2
EVENT_LEFT_LEAVE equ 4
LEFT        equ 1

int16:
        cmp word [cs:target_on], 0
        je .chain
        cmp ah, 0x00
        je .read
        cmp ah, 0x10
        je .read
        cmp ah, 0x01
        je .peek
        cmp ah, 0x11
        je .peek
.chain: jmp far [cs:old16]
.peek:  push ax                         ; a key waiting: if it is ours, take it and say none is
        pushf
        call far [cs:old16]
        jz .none
        call our_key
        jc .took
        add sp, 2                       ; (not ours: as the BIOS said)
        push bp
        mov bp, sp
        and word [bp + 6], ~0x40        ; ZF clear
        pop bp
        iret
.took:  pop ax
        push ax
        xor ah, ah
        pushf
        call far [cs:old16]
        pop ax
        jmp .peek
.none:  pop ax
        push bp
        mov bp, sp
        or word [bp + 6], 0x40          ; ZF set: no key
        pop bp
        iret
.read:  push ax                         ; reading: ours are taken out and the next one read
.again: pop ax
        push ax
        pushf
        call far [cs:old16]
        call our_key
        jc .again
        add sp, 2
        iret

our_key:                                ; AX a key: CF set (and counted) if it is one of ours
        cmp ax, KEY_TAB
        jne .back
        inc word [cs:tab_seq]
        stc
        ret
.back:  cmp ax, KEY_BACKTAB
        jne .enter
        inc word [cs:back_seq]
        stc
        ret
.enter: cmp word [cs:hit_target], 0xFFFF
        je .no
        cmp ax, KEY_ENTER
        je .go
        cmp ax, KEY_PAD_ENTER
        jne .no
.go:    inc word [cs:attack_seq]
        mov byte [cs:t_click], 1
        stc
        ret
.no:    clc
        ret

; TARGET_CLICK: (in PROBE_SCROLL, DS = the game's) Enter on the chosen enemy: a left click at its feet
target_click:
        cmp byte [cs:t_click], 0
        je .ret
        mov byte [cs:t_click], 0
        cmp word [cs:game_mask], 0
        je .ret
        mov bx, [cs:hit_target]
        cmp bx, MAP_COUNT - 1
        ja .ret
        shl bx, 5
        mov cx, [bx + MAP_THINGS + 9]   ; its feet, on the map
        mov dx, [bx + MAP_THINGS + 11]
        sub cx, [CAM_X]
        sub dx, [CAM_Y]
        sub dx, 8                       ; (a little above them)
        cmp cx, 1
        jl .ret
        cmp cx, 0x13E
        jg .ret
        cmp dx, 1
        jl .ret
        cmp dx, 0xC6
        jg .ret
        mov [cs:t_x], cx
        mov [cs:t_y], dx
        mov ax, [cs:main_ticks]
        add ax, HIT_PASSES
        mov [cs:hit_until], ax
        mov byte [cs:hit_forced], 1
        mov ax, 4                       ; the pointer there
        mov cx, [cs:t_x]
        mov dx, [cs:t_y]
        int 0x33
        pusha                           ; and a click
        push ds
        push es
        mov ax, EVENT_LEFT_PRESS
        mov bx, LEFT
        mov cx, [cs:t_x]
        mov dx, [cs:t_y]
        xor si, si
        xor di, di
        call far [cs:game_handler]
        pop es
        pop ds
        popa
        pusha
        push ds
        push es
        mov ax, EVENT_LEFT_LEAVE
        xor bx, bx
        mov cx, [cs:t_x]
        mov dx, [cs:t_y]
        xor si, si
        xor di, di
        call far [cs:game_handler]
        pop es
        pop ds
        popa
.ret:   ret

; PROBE_HIT: INT VEC_HIT replaces "push bp / mov bp,sp / sub sp,10h" (6 bytes: INT + 4 NOPs) at the
; start of the routine that finds the thing under the pointer (camera x, y, x, y on screen; the
; thing, or FFFFh): for a moment after TARGET_CLICK, the chosen enemy, wherever the pointer is.
probe_hit:
        cmp byte [cs:hit_forced], 0
        je .plain
        push ax
        mov ax, [cs:main_ticks]
        sub ax, [cs:hit_until]
        pop ax
        jns .over
        push bp                         ; (the caller's flags back: the INT turned interrupts off,
        mov bp, sp                      ;   and a RETF leaves them so; the game then ran on without
        push word [bp + 6]              ;   its timer, a walk to the enemy frozen till something
        popf                            ;   turned them on again)
        pop bp
        add sp, 6                       ; (the interrupt's frame: back to the caller, the enemy)
        mov ax, [cs:hit_target]
        retf
.over:  mov byte [cs:hit_forced], 0
.plain: pop word [cs:h_resume]
        pop word [cs:h_resume + 2]
        popf
        push bp
        mov bp, sp
        sub sp, 0x10
        jmp far [cs:h_resume]

old16      dd 0
t_click    db 0
hit_forced db 0
hit_until  dw 0
h_resume   dd 0

old33        dd 0
game_handler dd 0
game_mask    dw 0
centre       dw CENTRE_OFF, 0
s_resume     dd 0
s_resume_fl  dw 0
drag         db 0               ; 0: no drag; 1: the right button held, not moved yet; 2: dragging
drag_mid     db 0               ; 1: dragging with the wheel pressed
drag_new     db 0
drag_x       dw 0               ; where it was pressed
drag_y       dw 0
cam0_x       dw 0               ; the view's top left then
cam0_y       dw 0
pan_x_done   dw 0
pan_y_done   dw 0

loader     dw LOADER_OFF, 0
resume     dd 0
resume_fl  dw 0
floor_ret  dd 0
floor_frame dw 0
floor_kind db 0
floor_busy db 0
dark_ready db 0
mirror     db 0
r_n        db 0
sc_index   db 0
sc_mask    db 0
gc_index   db 0
gc_regs    db 1, 3, 4, 5, 8
gc_saved   times 5 db 0
zero       dw 0
game_ds    dw 0
load_seg   dw 0
clip_x0    dw 0
clip_y0    dw 0
clip_x1    dw 0
clip_y1    dw 0
v_seg      dw 0
v_x0       dw 0
v_y0       dw 0
v_row      dw 0
cam_x      dw 0
cam_y      dw 0
fig_x      dw 0
fig_y      dw 0
frame      dw 0
f_w        dw 0
f_bottom   dw 0
f_y        dw 0
r_x        dw 0
row_at     dw 0
s_first    dw 0
s_last     dw 0
best_d     dd 0
diffs      times 3 db 0
lit_sum    dw 0
lit_most   dw 0
best_c     db 0
want       times 3 db 0
shadow_tab times MAP_COUNT db 0
dark       times 256 db 0
dac        times 768 db 0

align 16
ring:   times NENT*ESIZE db 0
tbuf:   times TSIZE db 0
resident_end:

install:                        ; DS = ES = PSP, CS = the image
        mov [cs:psp], es
        push cs
        pop ds
        mov si, all_vectors     ; the vectors must be free
        mov cx, 42
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
        mov ax, 2500h + VEC_WIN
        mov dx, probe_win
        int 21h
        mov ax, 2500h + VEC_LOOK
        mov dx, probe_look
        int 21h
        mov ax, 2500h + VEC_UNLOOK
        mov dx, probe_unlook
        int 21h
        mov ax, 2500h + VEC_NEXT
        mov dx, probe_next
        int 21h
        mov ax, 2500h + VEC_RING_AC
        mov dx, probe_ring_ac
        int 21h
        mov ax, 2500h + VEC_RING_SAVE
        mov dx, probe_ring_save
        int 21h
        mov ax, 2500h + VEC_WEAPON
        mov dx, probe_weapon
        int 21h
        mov ax, 2500h + VEC_MOVE
        mov dx, probe_move
        int 21h
        mov ax, 2500h + VEC_PICK
        mov dx, probe_pick
        int 21h
        mov ax, 2500h + VEC_USE_ITEM
        mov dx, probe_use_item
        int 21h
        mov ax, 2500h + VEC_TWO
        mov dx, probe_two
        int 21h
        mov ax, 2500h + VEC_DOUBLE
        mov dx, probe_double
        int 21h
        mov ax, 2500h + VEC_GRACE_CAST
        mov dx, probe_grace_cast
        int 21h
        mov ax, 2500h + VEC_GRACE_EFFECT
        mov dx, probe_grace_effect
        int 21h
        mov ax, 2500h + VEC_GRACE_ABILITY
        mov dx, probe_grace_ability
        int 21h
        mov ax, 2500h + VEC_NAMES_SIZE
        mov dx, probe_names_size
        int 21h
        mov ax, 2500h + VEC_NAMES_FILL
        mov dx, probe_names_fill
        int 21h
        mov ax, 2500h + VEC_STEALTH
        mov dx, probe_stealth
        int 21h
        mov ax, 2500h + VEC_TYPES_SIZE
        mov dx, probe_types_size
        int 21h
        mov ax, 2500h + VEC_TYPES_FILL
        mov dx, probe_types_fill
        int 21h
        mov ax, 2500h + VEC_LEVEL
        mov dx, probe_level
        int 21h
        mov ax, 2500h + VEC_HD_ROLL
        mov dx, probe_hd_roll
        int 21h
        mov ax, 2500h + VEC_HD_CON
        mov dx, probe_hd_con
        int 21h
        mov ax, 2500h + VEC_THIEF_SKILL
        mov dx, probe_thief_skill
        int 21h
        mov ax, 2500h + VEC_TWO_HANDED
        mov dx, probe_two_handed
        int 21h
        mov ax, 2500h + VEC_SPELL_TEXT
        mov dx, probe_spell_text
        int 21h
        mov ax, 2500h + VEC_CHUNK_ID
        mov dx, probe_chunk_id
        int 21h
        mov ax, 2500h + VEC_FLOOR_ALL
        mov dx, probe_floor_all
        int 21h
        mov ax, 2500h + VEC_FLOOR_RECT
        mov dx, probe_floor_rect
        int 21h
        mov ax, 2500h + VEC_REDRAW
        mov dx, probe_redraw
        int 21h
        mov ax, 2500h + VEC_REDRAW_ALL
        mov dx, probe_redraw_all
        int 21h
        mov ax, 2500h + VEC_SCROLL
        mov dx, probe_scroll
        int 21h
        mov ax, 2500h + VEC_HIT
        mov dx, probe_hit
        int 21h
        mov ax, 3516h           ; the keyboard's (TARGETING)
        int 21h
        mov [old16], bx
        mov [old16 + 2], es
        mov ax, 2516h
        mov dx, int16
        int 21h
        mov ax, 3533h           ; the mouse driver's (SCROLLING), if there is one
        int 21h
        mov ax, es
        or ax, bx
        jz .no_mouse
        mov [old33], bx
        mov [old33 + 2], es
        mov ax, 2533h
        mov dx, int33
        int 21h
.no_mouse:
        mov ax, 3521h           ; DOS itself last: opening the objects file (PROBE_DOS_OPEN)
        int 21h
        mov [old21], bx
        mov [old21 + 2], es
        mov ax, 2521h
        mov dx, probe_dos_open
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
busy    db 'DSCLOG: interrupts 60h-65h or DBh-FEh are in use (already loaded?). Not loaded.', 13, 10, '$'
all_vectors db VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG, VEC_CHAR, VEC_TURN, VEC_USE, VEC_VIEW, VEC_WIN, VEC_LOOK, VEC_UNLOOK, VEC_NEXT, VEC_RING_AC, VEC_RING_SAVE, VEC_WEAPON, VEC_MOVE, VEC_PICK, VEC_USE_ITEM, VEC_TWO, VEC_DOUBLE, VEC_GRACE_CAST, VEC_GRACE_EFFECT, VEC_GRACE_ABILITY, VEC_NAMES_SIZE, VEC_NAMES_FILL, VEC_STEALTH, VEC_TYPES_SIZE, VEC_TYPES_FILL, VEC_LEVEL, VEC_HD_ROLL, VEC_HD_CON, VEC_THIEF_SKILL, VEC_TWO_HANDED, VEC_SPELL_TEXT, VEC_CHUNK_ID, VEC_FLOOR_ALL, VEC_FLOOR_RECT, VEC_REDRAW, VEC_REDRAW_ALL, VEC_SCROLL, VEC_HIT

        align 16, db 0
image_len equ $ - $$
file_len  equ image_len + 32
