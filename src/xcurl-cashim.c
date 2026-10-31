/* XCurl.dll CA-injecting shim.
 * The game's libHttpClient CurlProvider never sets CURLOPT_CAINFO, and this
 * OpenSSL libcurl ignores CURL_CA_BUNDLE/SSL_CERT_FILE env (its compiled default
 * CAINFO overrides OpenSSL's env paths) and has no Windows app-dir auto-search.
 * So TLS verify (enforced in-game) fails. This shim exports the 16 curl_* symbols
 * the game resolves, forwards them to the REAL libcurl (shipped as xcurl_real.dll
 * beside this DLL), and intercepts curl_easy_init to set CURLOPT_CAINFO to
 * "cacert.pem" sitting next to this DLL — fully self-contained.
 *
 * It ALSO carries a diagnostic (only when XCURL_LOG=1 in the env): besides the
 * "DONE rc=.. http=.. url=.." line per request, it captures the RESPONSE BODY of
 * the in-game social endpoints (peoplehub/social/profile/persona/realms/club)
 * that ride XCurl and are invisible to WinHTTP traces, so we can see why opening
 * another player's profile / Realms spins forever even though the HTTP is 200.
 * The body capture wraps CURLOPT_WRITEFUNCTION ONLY for those all-listed hosts —
 * every other handle (login/PlayFab/marketplace/multiplayer) is passed straight
 * through unchanged, so a bug here cannot regress anything that already works.
 * When XCURL_LOG != 1 the shim does nothing beyond CA injection + URL rewrite. */
#include <windows.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>

typedef void CURL; typedef void CURLM;
#define CURLOPT_CAINFO        10065
#define CURLOPT_URL           10002
#define CURLOPT_WRITEDATA     10001
#define CURLOPT_WRITEFUNCTION 20011
#define CURLINFO_RESPONSE_CODE 0x200002
#define CURLINFO_EFFECTIVE_URL 0x100001

typedef size_t (*wfn_t)(char*, size_t, size_t, void*);

static CRITICAL_SECTION g_cs;
static int  g_cs_ready = 0;
static HMODULE g_real = NULL;
static char g_ca[1024];
static char g_logpath[1024];
static int  g_log = 0;          /* enabled when XCURL_LOG=1 in the env */

static void xlog(const char* fmt, ...){
    if (!g_log || !g_logpath[0]) return;
    FILE* f = fopen(g_logpath, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fclose(f);
}

static CURL* (*r_easy_init)(void);
static void  (*r_easy_cleanup)(CURL*);
static int   (*r_easy_setopt)(CURL*, int, void*);
static int   (*r_easy_getinfo)(CURL*, int, void*);
static const char* (*r_easy_strerror)(int);
static int   (*r_global_init)(long);
static void  (*r_global_cleanup)(void);
static CURLM*(*r_multi_init)(void);
static int   (*r_multi_cleanup)(CURLM*);
static int   (*r_multi_add)(CURLM*, CURL*);
static int   (*r_multi_remove)(CURLM*, CURL*);
static int   (*r_multi_perform)(CURLM*, int*);
static int   (*r_multi_poll)(CURLM*, void*, unsigned, int, int*);
static int   (*r_multi_wait)(CURLM*, void*, unsigned, int, int*);
static void* (*r_multi_info_read)(CURLM*, int*);
static void* (*r_slist_append)(void*, const char*);
static void  (*r_slist_free_all)(void*);

static void init_once(void){
    if (g_real) return;
    if (!g_cs_ready) return;            /* DllMain not run yet (shouldn't happen) */
    EnterCriticalSection(&g_cs);
    if (!g_real){
        char dir[1024]; HMODULE self=NULL;
        /* FROM_ADDRESS|UNCHANGED_REFCOUNT — resolve this DLL's own path */
        GetModuleHandleExA(0x4|0x2,(LPCSTR)&init_once,&self);
        dir[0]=0;
        if (self) GetModuleFileNameA(self, dir, sizeof dir);
        char* s=strrchr(dir,'\\');
        if (s){
            size_t n=(size_t)(s-dir)+1;
            memcpy(g_ca,dir,n); strcpy(g_ca+n,"cacert.pem");
            memcpy(g_logpath,dir,n); strcpy(g_logpath+n,"xcurl.log");
            char rp[1024]; memcpy(rp,dir,n); strcpy(rp+n,"xcurl_real.dll");
            g_real=LoadLibraryA(rp);
        }
        if (!g_real) { g_ca[0]=0; strcpy(g_ca,"cacert.pem"); g_real=LoadLibraryA("xcurl_real.dll"); }
        { char v[8]={0}; if (GetEnvironmentVariableA("XCURL_LOG",v,sizeof v) && v[0]=='1') g_log=1; }
        xlog("=== xcurl shim init: real=%p ca=%s ===\n", (void*)g_real, g_ca);
        if (g_real){
            HMODULE r=g_real;
            r_easy_init      =(void*)GetProcAddress(r,"curl_easy_init");
            r_easy_cleanup   =(void*)GetProcAddress(r,"curl_easy_cleanup");
            r_easy_setopt    =(void*)GetProcAddress(r,"curl_easy_setopt");
            r_easy_getinfo   =(void*)GetProcAddress(r,"curl_easy_getinfo");
            r_easy_strerror  =(void*)GetProcAddress(r,"curl_easy_strerror");
            r_global_init    =(void*)GetProcAddress(r,"curl_global_init");
            r_global_cleanup =(void*)GetProcAddress(r,"curl_global_cleanup");
            r_multi_init     =(void*)GetProcAddress(r,"curl_multi_init");
            r_multi_cleanup  =(void*)GetProcAddress(r,"curl_multi_cleanup");
            r_multi_add      =(void*)GetProcAddress(r,"curl_multi_add_handle");
            r_multi_remove   =(void*)GetProcAddress(r,"curl_multi_remove_handle");
            r_multi_perform  =(void*)GetProcAddress(r,"curl_multi_perform");
            r_multi_poll     =(void*)GetProcAddress(r,"curl_multi_poll");
            r_multi_wait     =(void*)GetProcAddress(r,"curl_multi_wait");
            r_multi_info_read=(void*)GetProcAddress(r,"curl_multi_info_read");
            r_slist_append   =(void*)GetProcAddress(r,"curl_slist_append");
            r_slist_free_all =(void*)GetProcAddress(r,"curl_slist_free_all");
        }
    }
    LeaveCriticalSection(&g_cs);
}

/* per-handle slot: URL label + (diagnostic) response-body capture state */
#define XMAP_N    256
#define XBODY_CAP 7168
struct hslot {
    CURL*  h;
    char   url[256];
    int    watch;       /* URL is an in-game social endpoint -> capture body */
    wfn_t  real_wf;     /* game's real write callback (NULL until it sets one) */
    void*  real_wd;     /* game's real write userdata */
    int    wrapped;     /* our trampoline is installed as this handle's WRITEFUNCTION */
    int    blen;        /* bytes captured into body[] */
    char   body[XBODY_CAP];
};
static struct hslot g_slot[XMAP_N];

static struct hslot* slot_find(CURL* h, int create){
    int i, free_i=-1;
    for(i=0;i<XMAP_N;i++){ if(g_slot[i].h==h) return &g_slot[i]; if(free_i<0&&!g_slot[i].h)free_i=i; }
    if(create && free_i>=0){ memset(&g_slot[free_i],0,sizeof g_slot[free_i]); g_slot[free_i].h=h; return &g_slot[free_i]; }
    return NULL;
}
static void slot_del(CURL* h){
    int i; if(!g_cs_ready) return;
    EnterCriticalSection(&g_cs);
    for(i=0;i<XMAP_N;i++) if(g_slot[i].h==h){ memset(&g_slot[i],0,sizeof g_slot[i]); break; }
    LeaveCriticalSection(&g_cs);
}

/* The in-game social/profile surfaces whose responses we want to see. Anything
 * NOT on this list is never touched by the body-capture wrap. */
static int url_watched(const char* u){
    return u && ( strstr(u,"peoplehub.xboxlive")  || strstr(u,"social.xboxlive")
               || strstr(u,"profile.xboxlive")    || strstr(u,"persona")
               || strstr(u,"realms.minecraft")    || strstr(u,"clubhub")
               || strstr(u,"clubaccounts")        || strstr(u,"userpresence") );
}

/* one-line body dump (newlines/CRs flattened so the log stays grep-able) */
static void xlog_body(struct hslot* s){
    int i; char* p;
    if(!g_log || !s || s->blen<=0) return;
    for(p=s->body,i=0;i<s->blen;i++,p++) if(*p=='\n'||*p=='\r'||*p=='\t') *p=' ';
    xlog("BODY[%d%s] %s | %s\n", s->blen, (s->blen>=XBODY_CAP-1)?"+":"", s->url, s->body);
}

/* our WRITEFUNCTION trampoline: copy (capped) into the slot for logging, then
 * forward verbatim to the game's real callback and return ITS value */
static size_t write_tramp(char* ptr, size_t sz, size_t nm, void* ud){
    struct hslot* s = (struct hslot*)ud;
    size_t n = sz*nm;
    if(s){
        if(s->watch && s->blen < XBODY_CAP-1){
            int room = XBODY_CAP-1 - s->blen;
            int cp = (n < (size_t)room) ? (int)n : room;
            memcpy(s->body + s->blen, ptr, cp);
            s->blen += cp; s->body[s->blen]=0;
        }
        if(s->real_wf) return s->real_wf(ptr,sz,nm,s->real_wd);
    }
    return n;   /* no real callback known: pretend fully consumed */
}

__declspec(dllexport) CURL* curl_easy_init(void){
    init_once();
    if(!r_easy_init) return NULL;
    CURL* h=r_easy_init();
    if(h && r_easy_setopt && g_ca[0]) r_easy_setopt(h, CURLOPT_CAINFO, g_ca);
    return h;
}
__declspec(dllexport) void curl_easy_cleanup(CURL* h){ init_once(); slot_del(h); if(r_easy_cleanup) r_easy_cleanup(h); }
__declspec(dllexport) int  curl_easy_setopt(CURL* h,int o,void* v){
    init_once();
    if(o==CURLOPT_URL && v){
        const char* url=(const char*)v;
        /* Minecraft builds Xbox People Hub URLs with an empty owner —
         * /users/xuid()/people/... — which peoplehub rejects with HTTP 400
         * "Owner XUID is required", leaving the in-game Friends list/search
         * empty. The caller is implied by the XBL token, so rewrite the empty
         * owner to "me" (verified: peoplehub returns 200 for /users/me/...).
         * The rewritten URL must outlive this call: this libcurl keeps the
         * CURLOPT_URL pointer (a stack/transient copy dangles and faults in
         * perform). Allocate it and leak it — tiny and only on Friends calls. */
        const char* eff=url;
        const char* bad=strstr(url,"/users/xuid()/");
        char* fixed=NULL;
        if(bad){
            size_t pre=(size_t)(bad-url);
            const char* rest=bad+14;              /* strlen("/users/xuid()/") */
            size_t need=pre+10+strlen(rest)+1;    /* 10 = strlen("/users/me/") */
            fixed=(char*)malloc(need);
            if(fixed){
                memcpy(fixed,url,pre);
                memcpy(fixed+pre,"/users/me/",10);
                strcpy(fixed+pre+10,rest);
                eff=fixed;
                xlog("rewrote empty xuid() -> me: %s\n", fixed);
            }
        }
        if(g_log){
            EnterCriticalSection(&g_cs);
            struct hslot* s=slot_find(h,1);
            if(s){
                strncpy(s->url,eff,255); s->url[255]=0;
                s->blen=0; s->body[0]=0;
                s->watch=url_watched(eff);
                /* if WRITEFUNCTION was already set on this handle and the URL is
                 * now a watched one, install the trampoline retroactively */
                if(s->watch && s->real_wf && !s->wrapped && r_easy_setopt){
                    r_easy_setopt(h,CURLOPT_WRITEFUNCTION,(void*)write_tramp);
                    r_easy_setopt(h,CURLOPT_WRITEDATA,(void*)s);
                    s->wrapped=1;
                }
                /* reused handle now points at a NON-watched URL but still carries
                 * our trampoline from a prior request: restore the real callback
                 * so we never feed the game's writer our slot as its userdata */
                else if(!s->watch && s->wrapped && r_easy_setopt){
                    r_easy_setopt(h,CURLOPT_WRITEFUNCTION,(void*)s->real_wf);
                    r_easy_setopt(h,CURLOPT_WRITEDATA,s->real_wd);
                    s->wrapped=0;
                }
            }
            LeaveCriticalSection(&g_cs);
        }
        return r_easy_setopt?r_easy_setopt(h,o,(void*)eff):-1;
    }
    /* Body-capture wrap — ONLY active under XCURL_LOG and ONLY for watched URLs.
     * Everything else falls through to the real libcurl untouched. */
    if(g_log && o==CURLOPT_WRITEFUNCTION){
        EnterCriticalSection(&g_cs);
        struct hslot* s=slot_find(h,1);
        if(s){
            s->real_wf=(wfn_t)v;
            if(s->watch && v && r_easy_setopt){
                int rc=r_easy_setopt(h,CURLOPT_WRITEFUNCTION,(void*)write_tramp);
                r_easy_setopt(h,CURLOPT_WRITEDATA,(void*)s);   /* re-assert our userdata */
                s->wrapped=1;
                LeaveCriticalSection(&g_cs);
                return rc;
            }
            s->wrapped=0;   /* not wrapping this handle: real WRITEFUNCTION below */
        }
        LeaveCriticalSection(&g_cs);
        return r_easy_setopt?r_easy_setopt(h,o,v):-1;
    }
    if(g_log && o==CURLOPT_WRITEDATA){
        EnterCriticalSection(&g_cs);
        struct hslot* s=slot_find(h,1);
        if(s){
            s->real_wd=v;
            if(s->wrapped && r_easy_setopt){
                r_easy_setopt(h,CURLOPT_WRITEDATA,(void*)s);   /* keep slot as userdata */
                LeaveCriticalSection(&g_cs);
                return 0;
            }
        }
        LeaveCriticalSection(&g_cs);
        return r_easy_setopt?r_easy_setopt(h,o,v):-1;
    }
    return r_easy_setopt?r_easy_setopt(h,o,v):-1;
}
__declspec(dllexport) int  curl_easy_getinfo(CURL* h,int o,void* v){ init_once(); return r_easy_getinfo?r_easy_getinfo(h,o,v):-1; }
__declspec(dllexport) const char* curl_easy_strerror(int c){ init_once(); return r_easy_strerror?r_easy_strerror(c):""; }
__declspec(dllexport) int  curl_global_init(long f){ init_once(); return r_global_init?r_global_init(f):-1; }
__declspec(dllexport) void curl_global_cleanup(void){ init_once(); if(r_global_cleanup) r_global_cleanup(); }
__declspec(dllexport) CURLM* curl_multi_init(void){ init_once(); return r_multi_init?r_multi_init():NULL; }
__declspec(dllexport) int  curl_multi_cleanup(CURLM* m){ init_once(); return r_multi_cleanup?r_multi_cleanup(m):-1; }
__declspec(dllexport) int  curl_multi_add_handle(CURLM* m,CURL* h){ init_once(); return r_multi_add?r_multi_add(m,h):-1; }
__declspec(dllexport) int  curl_multi_remove_handle(CURLM* m,CURL* h){ init_once(); return r_multi_remove?r_multi_remove(m,h):-1; }
__declspec(dllexport) int  curl_multi_perform(CURLM* m,int* n){ init_once(); return r_multi_perform?r_multi_perform(m,n):-1; }
__declspec(dllexport) int  curl_multi_poll(CURLM* m,void* e,unsigned ne,int t,int* nr){ init_once(); return r_multi_poll?r_multi_poll(m,e,ne,t,nr):-1; }
__declspec(dllexport) int  curl_multi_wait(CURLM* m,void* e,unsigned ne,int t,int* nr){ init_once(); return r_multi_wait?r_multi_wait(m,e,ne,t,nr):-1; }
__declspec(dllexport) void* curl_multi_info_read(CURLM* m,int* q){
    init_once();
    void* msg = r_multi_info_read ? r_multi_info_read(m,q) : NULL;
    /* CURLMsg { int msg; CURL* easy_handle; union { void* whatever; int result; } data; } */
    if(g_log && msg){
        struct { int msg; CURL* e; void* res; } *mm = msg;
        if(mm->msg==1 /*CURLMSG_DONE*/ && mm->e){
            long code=0; if(r_easy_getinfo) r_easy_getinfo(mm->e,CURLINFO_RESPONSE_CODE,&code);
            int rc=(int)(LONG_PTR)mm->res;
            EnterCriticalSection(&g_cs);
            struct hslot* s=slot_find(mm->e,0);
            xlog("DONE rc=%d http=%ld url=%s\n", rc, code, s?s->url:"?");
            if(s && s->watch){ xlog_body(s); s->blen=0; s->body[0]=0; }
            LeaveCriticalSection(&g_cs);
        }
    }
    return msg;
}
__declspec(dllexport) void* curl_slist_append(void* l,const char* s){ init_once(); return r_slist_append?r_slist_append(l,s):NULL; }
__declspec(dllexport) void curl_slist_free_all(void* l){ init_once(); if(r_slist_free_all) r_slist_free_all(l); }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID v){
    (void)h;(void)v;
    if(reason==DLL_PROCESS_ATTACH){ InitializeCriticalSection(&g_cs); g_cs_ready=1; }
    return TRUE;
}
