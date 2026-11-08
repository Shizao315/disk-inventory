#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winioctl.h>
#include <commdlg.h>
#include <shlobj.h>
#include <shellapi.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <climits>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include "report_template.h"

static const wchar_t* VERSION=L"0.1.0-test";
struct Options { std::vector<std::wstring> roots; std::wstring output; bool hidden=false; std::wstring engine=L"auto"; };
struct Node {
 int parent=-1; std::wstring name; bool dir=false,known=true; uint64_t bytes=0;
 uint64_t created=0,modified=0; DWORD attrs=0,error=0; std::string state="ok";
};
struct Inventory {
 std::vector<Node> nodes; std::vector<std::wstring> dirs;
 std::vector<std::string> engines; std::vector<std::string> notes;
 uint64_t files=0,folders=0,errors=0,skipped=0,hiddenSkipped=0;
 bool cancelled=false; double seconds=0; std::wstring started,finished;
};
static std::atomic<bool> cancelScan{false},running{false};
static std::atomic<uint64_t> progressFiles{0},progressDirs{0};
static HWND mainWindow,rootEdit,outEdit,hiddenCheck,statusText,scanButton,cancelButton,openButton,adminButton;
static HFONT uiFont;
static std::wstring lastOutput;
static Options activeOptions;
static std::string lastFailure;

static std::string utf8(const std::wstring& s) {
 if(s.empty())return {}; int n=WideCharToMultiByte(CP_UTF8,0,s.data(),(int)s.size(),nullptr,0,nullptr,nullptr);
 std::string r(n,'\0');WideCharToMultiByte(CP_UTF8,0,s.data(),(int)s.size(),r.data(),n,nullptr,nullptr);return r;
}
static std::wstring wide(const std::string& s) {
 if(s.empty())return {};int n=MultiByteToWideChar(CP_UTF8,0,s.data(),(int)s.size(),nullptr,0);
 std::wstring r(n,L'\0');MultiByteToWideChar(CP_UTF8,0,s.data(),(int)s.size(),r.data(),n);return r;
}
static std::wstring errorText(DWORD code) {
 wchar_t* p=nullptr;FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER|FORMAT_MESSAGE_FROM_SYSTEM|FORMAT_MESSAGE_IGNORE_INSERTS,nullptr,code,0,(LPWSTR)&p,0,nullptr);
 std::wstring r=p?p:L"Windows error";if(p)LocalFree(p);while(!r.empty()&&(r.back()==L'\r'||r.back()==L'\n'))r.pop_back();return r+L" ("+std::to_wstring(code)+L")";
}
static std::wstring extended(const std::wstring& p){if(p.rfind(L"\\\\?\\",0)==0)return p;if(p.rfind(L"\\\\",0)==0)return L"\\\\?\\UNC\\"+p.substr(2);return L"\\\\?\\"+p;}
static std::wstring normalize(const std::wstring& path){
 std::wstring p=path;std::replace(p.begin(),p.end(),L'/',L'\\');
 if(p.rfind(L"\\\\?\\UNC\\",0)==0)p=L"\\\\"+p.substr(8);else if(p.rfind(L"\\\\?\\",0)==0)p=p.substr(4);
 DWORD n=GetFullPathNameW(p.c_str(),0,nullptr,nullptr);if(!n)throw std::runtime_error("Invalid path");std::wstring r(n,L'\0');DWORD count=GetFullPathNameW(p.c_str(),n,r.data(),nullptr);if(!count||count>=n)throw std::runtime_error("Invalid absolute path");r.resize(count);
 while(r.size()>3&&r.back()==L'\\')r.pop_back();return r;
}
static std::wstring join(const std::wstring& a,const std::wstring& b){return a+(a.empty()||a.back()!=L'\\'?L"\\":L"")+b;}
static bool equalPath(const std::wstring&a,const std::wstring&b){return CompareStringOrdinal(a.c_str(),(int)a.size(),b.c_str(),(int)b.size(),TRUE)==CSTR_EQUAL;}
static bool containsPath(const std::wstring& root,const std::wstring& p){return p.size()>=root.size()&&CompareStringOrdinal(root.c_str(),(int)root.size(),p.c_str(),(int)root.size(),TRUE)==CSTR_EQUAL&&(p.size()==root.size()||root.back()==L'\\'||p[root.size()]==L'\\');}
static uint64_t ticks(FILETIME ft){return (uint64_t(ft.dwHighDateTime)<<32)|ft.dwLowDateTime;}
static std::wstring timestamp(uint64_t value=0){
 FILETIME ft;if(value){ft.dwLowDateTime=DWORD(value);ft.dwHighDateTime=DWORD(value>>32);}else GetSystemTimeAsFileTime(&ft);
 SYSTEMTIME st;if(!FileTimeToSystemTime(&ft,&st))return L"";wchar_t b[40];swprintf(b,40,L"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",st.wYear,st.wMonth,st.wDay,st.wHour,st.wMinute,st.wSecond,st.wMilliseconds);return b;
}
static bool isAdmin(){BOOL value=FALSE;SID_IDENTIFIER_AUTHORITY nt=SECURITY_NT_AUTHORITY;PSID sid=nullptr;if(AllocateAndInitializeSid(&nt,2,SECURITY_BUILTIN_DOMAIN_RID,DOMAIN_ALIAS_RID_ADMINS,0,0,0,0,0,0,&sid)){CheckTokenMembership(nullptr,sid,&value);FreeSid(sid);}return value!=FALSE;}
static std::string json(const std::wstring& text){
 std::string s=utf8(text),r="\"";for(unsigned char c:s){switch(c){case '"':r+="\\\"";break;case '\\':r+="\\\\";break;case '\n':r+="\\n";break;case '\r':r+="\\r";break;case '\t':r+="\\t";break;case '<':r+="\\u003c";break;case '>':r+="\\u003e";break;case '&':r+="\\u0026";break;default:if(c<32){char b[7];snprintf(b,sizeof(b),"\\u%04x",c);r+=b;}else r+=char(c);}}return r+'"';
}
static std::string js(const std::string& s){return json(wide(s));}
static void writeAll(HANDLE f,const char* p,size_t count){while(count){DWORD written=0,take=DWORD(std::min<size_t>(count,1024*1024));if(!WriteFile(f,p,take,&written,nullptr)||written!=take)throw std::runtime_error("Cannot write report: "+utf8(errorText(GetLastError())));p+=written;count-=written;}}
static void writeAll(HANDLE f,const std::string& s){writeAll(f,s.data(),s.size());}
static int addNode(Inventory& inv,Node node,const std::wstring& path){int id=(int)inv.nodes.size();if(id==INT_MAX)throw std::runtime_error("Too many records");if(node.dir){inv.folders++;progressDirs=inv.folders;}else{inv.files++;progressFiles=inv.files;}inv.dirs.push_back(node.dir?path:L"");inv.nodes.push_back(std::move(node));return id;}
static bool excludedOutput(const std::wstring& path,const Options& o){return equalPath(path,o.output)||equalPath(path,o.output+L".tmp");}
static bool linkDirectory(DWORD attrs,DWORD tag){return (attrs&FILE_ATTRIBUTE_DIRECTORY)&&(attrs&FILE_ATTRIBUTE_REPARSE_POINT)&&(tag&0x20000000);}
static void setMetadata(Node& n,const WIN32_FIND_DATAW& f){n.attrs=f.dwFileAttributes;n.created=ticks(f.ftCreationTime);n.modified=ticks(f.ftLastWriteTime);if(!n.dir){n.bytes=(uint64_t(f.nFileSizeHigh)<<32)|f.nFileSizeLow;n.known=true;}if(n.state=="metadata_pending")n.state="ok";}
static bool rootMetadata(const std::wstring& path,Node& n){
 HANDLE h=CreateFileW(extended(path).c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
 if(h==INVALID_HANDLE_VALUE)return false;BY_HANDLE_FILE_INFORMATION b{};bool ok=GetFileInformationByHandle(h,&b);CloseHandle(h);if(ok){n.attrs=b.dwFileAttributes;n.created=ticks(b.ftCreationTime);n.modified=ticks(b.ftLastWriteTime);}return ok;
}

// Each directory is enumerated once in a buffered native query. This obtains
// actual lengths/CreationTime/LastWriteTime and preserves hard-link names.
static void enumerateDirectory(Inventory& inv,int id,const Options& o,std::unordered_map<std::wstring,int>* existing=nullptr){
 const std::wstring path=inv.dirs[id];
 WIN32_FIND_DATAW f{};std::wstring pattern=join(extended(path),L"*");
 HANDLE h=FindFirstFileExW(pattern.c_str(),FindExInfoBasic,&f,FindExSearchNameMatch,nullptr,FIND_FIRST_EX_LARGE_FETCH);
 if(h==INVALID_HANDLE_VALUE&&GetLastError()==ERROR_INVALID_PARAMETER)h=FindFirstFileExW(pattern.c_str(),FindExInfoBasic,&f,FindExSearchNameMatch,nullptr,0);
 if(h==INVALID_HANDLE_VALUE){DWORD e=GetLastError();if(e!=ERROR_FILE_NOT_FOUND){inv.nodes[id].error=e;inv.nodes[id].state="unreadable";inv.errors++;}return;}
 DWORD endError=ERROR_NO_MORE_FILES;
 do{
  if(cancelScan.load())break;
  std::wstring name=f.cFileName;if(name==L"."||name==L"..")continue;
  const std::wstring full=join(path,name);if(excludedOutput(full,o))continue;
  if(!o.hidden&&(f.dwFileAttributes&FILE_ATTRIBUTE_HIDDEN)){inv.hiddenSkipped++;continue;}
  bool dir=(f.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)!=0;int found=-1;
  if(existing){auto it=existing->find(name);if(it!=existing->end()&&inv.nodes[it->second].dir==dir)found=it->second;}
  if(found<0){Node node;node.parent=id;node.name=name;node.dir=dir;setMetadata(node,f);found=addNode(inv,std::move(node),full);if(existing)(*existing)[name]=found;}
  else setMetadata(inv.nodes[found],f);
  if(linkDirectory(f.dwFileAttributes,f.dwReserved0)){inv.nodes[found].state="link_not_followed";inv.skipped++;}
 }while(FindNextFileW(h,&f)||(endError=GetLastError(),false));
 FindClose(h);if(!cancelScan.load()&&endError!=ERROR_NO_MORE_FILES){inv.nodes[id].error=endError;inv.nodes[id].state="enumeration_incomplete";inv.errors++;}
}

struct MftRecord {uint64_t frn,parent;DWORD attrs;std::wstring name;};
static bool readMft(const std::wstring& root,std::vector<MftRecord>& records,std::string& reason){
 std::wstring volume=L"\\\\.\\"+root.substr(0,2);HANDLE h=CreateFileW(volume.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);
 if(h==INVALID_HANDLE_VALUE){reason="MFT volume access: "+utf8(errorText(GetLastError()));return false;}
 struct EnumInput{uint64_t start;int64_t low,high;} input{0,0,INT64_MAX};
 std::vector<unsigned char> buffer(1024*1024);bool ok=true;
 while(!cancelScan.load()){
  DWORD got=0;if(!DeviceIoControl(h,FSCTL_ENUM_USN_DATA,&input,sizeof(input),buffer.data(),(DWORD)buffer.size(),&got,nullptr)){
   DWORD e=GetLastError();if(e!=ERROR_HANDLE_EOF){reason="MFT enumeration: "+utf8(errorText(e));ok=false;}break;
  }
  if(got<8){reason="Truncated MFT response";ok=false;break;}uint64_t next;memcpy(&next,buffer.data(),8);
  size_t offset=8;while(offset+8<=got){
   DWORD length;WORD major;memcpy(&length,buffer.data()+offset,4);memcpy(&major,buffer.data()+offset+4,2);
   if(length<60||offset+length>got||major!=2){reason="Unsupported or malformed USN record";ok=false;break;}
   const auto* p=buffer.data()+offset;MftRecord record;WORD nameLength,nameOffset;
   memcpy(&record.frn,p+8,8);memcpy(&record.parent,p+16,8);memcpy(&record.attrs,p+52,4);memcpy(&nameLength,p+56,2);memcpy(&nameOffset,p+58,2);
   if(nameOffset<60||nameOffset+nameLength>length||nameLength%2){reason="Malformed MFT name";ok=false;break;}
   record.name.resize(nameLength/2);memcpy(record.name.data(),p+nameOffset,nameLength);records.push_back(std::move(record));offset+=length;
  }
  if(!ok)break;if(next<=input.start){reason="Non-advancing MFT cursor";ok=false;break;}input.start=next;
 }
 CloseHandle(h);return ok;
}
static bool scanMft(Inventory& inv,const Options& o,const std::wstring& root,std::string& reason){
 std::vector<MftRecord> records;if(!readMft(root,records,reason))return false;
 if(cancelScan.load())return true;
 std::unordered_map<uint64_t,size_t> index;index.reserve(records.size());for(size_t i=0;i<records.size();i++)index[records[i].frn]=i;
 // Low 48 bits are the MFT record number; record 5 is the volume root.
 uint64_t rootFrn=0;for(auto&r:records)if((r.frn&0x0000ffffffffffffULL)==5&&(r.attrs&FILE_ATTRIBUTE_DIRECTORY)){rootFrn=r.frn;break;}
 if(!rootFrn){reason="MFT root missing";return false;}
 Node rn;rn.dir=true;rn.name=root;rootMetadata(root,rn);int rootId=addNode(inv,std::move(rn),root);
 std::unordered_map<uint64_t,int> ids;ids[rootFrn]=rootId;
 std::vector<int> states(records.size(),0);
 std::function<int(size_t,int)> resolve=[&](size_t i,int depth)->int{
  const MftRecord& r=records[i];auto present=ids.find(r.frn);if(present!=ids.end())return present->second;
  if(depth>1024||states[i]==1){inv.errors++;states[i]=2;return ids[r.frn]=-1;}
  if(states[i]==2)return -1;states[i]=1;
  if(!o.hidden&&(r.attrs&FILE_ATTRIBUTE_HIDDEN)){inv.hiddenSkipped++;states[i]=2;return ids[r.frn]=-1;}
  auto parent=index.find(r.parent);int pid=parent==index.end()?-1:resolve(parent->second,depth+1);
  if(parent==index.end()){inv.errors++;inv.notes.push_back("MFT parent not found: "+utf8(r.name));}
  if(pid<0||!inv.nodes[pid].dir||inv.nodes[pid].state=="link_not_followed"||inv.nodes[pid].state=="reparse_unverified"){states[i]=2;return ids[r.frn]=-1;}
  std::wstring full=join(inv.dirs[pid],r.name);if(excludedOutput(full,o)){states[i]=2;return ids[r.frn]=-1;}
  Node n;n.parent=pid;n.name=r.name;n.dir=(r.attrs&FILE_ATTRIBUTE_DIRECTORY)!=0;n.attrs=r.attrs;n.known=n.dir;n.state="metadata_pending";
  if(n.dir&&(n.attrs&FILE_ATTRIBUTE_REPARSE_POINT)){
   WIN32_FIND_DATAW f{};HANDLE h=FindFirstFileW(extended(full).c_str(),&f);if(h!=INVALID_HANDLE_VALUE){FindClose(h);if(linkDirectory(f.dwFileAttributes,f.dwReserved0)){n.state="link_not_followed";inv.skipped++;}}
   else {n.state="reparse_unverified";n.error=GetLastError();inv.skipped++;}
  }
  int id=addNode(inv,std::move(n),full);ids[r.frn]=id;states[i]=2;return id;
 };
 for(size_t i=0;i<records.size()&&!cancelScan.load();i++)resolve(i,0);
 records.clear();index.clear();ids.clear();states.clear();
 std::unordered_map<int,std::unordered_map<std::wstring,int>> children;
 for(size_t i=rootId+1;i<inv.nodes.size();i++)children[inv.nodes[i].parent][inv.nodes[i].name]=(int)i;
 for(size_t i=rootId;i<inv.nodes.size()&&!cancelScan.load();i++)if(inv.nodes[i].dir&&inv.nodes[i].state!="link_not_followed"&&inv.nodes[i].state!="reparse_unverified")enumerateDirectory(inv,(int)i,o,&children[(int)i]);
 for(size_t i=rootId;i<inv.nodes.size();i++)if(inv.nodes[i].state=="metadata_pending"){inv.nodes[i].state="metadata_unavailable";inv.errors++;}
 return true;
}
static void scanDirectory(Inventory& inv,const Options& o,const std::wstring& root){
 Node n;n.dir=true;n.name=root;if(!rootMetadata(root,n)){n.error=GetLastError();n.state="unreadable";inv.errors++;}int first=addNode(inv,std::move(n),root);
 // Selected root junctions are rejected rather than silently traversed.
 if(inv.nodes[first].attrs&FILE_ATTRIBUTE_REPARSE_POINT){WIN32_FIND_DATAW f{};HANDLE h=FindFirstFileW(extended(root).c_str(),&f);if(h!=INVALID_HANDLE_VALUE){FindClose(h);if(linkDirectory(f.dwFileAttributes,f.dwReserved0)){inv.nodes[first].state="link_not_followed";inv.skipped++;return;}}}
 for(size_t i=first;i<inv.nodes.size()&&!cancelScan.load();i++)if(inv.nodes[i].dir&&inv.nodes[i].state!="link_not_followed")enumerateDirectory(inv,(int)i,o);
}
static void cleanOptions(Options& o){
 o.output=normalize(o.output);std::vector<std::wstring> roots;
 for(auto raw:o.roots){auto p=normalize(raw);DWORD a=GetFileAttributesW(extended(p).c_str());if(a==INVALID_FILE_ATTRIBUTES||!(a&FILE_ATTRIBUTE_DIRECTORY))throw std::runtime_error("Not an accessible directory: "+utf8(p));
  bool covered=false;for(const auto&r:roots)if(containsPath(r,p)){covered=true;break;}if(covered)continue;
  roots.erase(std::remove_if(roots.begin(),roots.end(),[&](const auto&r){return containsPath(p,r);}),roots.end());roots.push_back(p);
 }
 if(roots.empty())throw std::runtime_error("Select at least one directory");o.roots=std::move(roots);
 if(o.engine!=L"auto"&&o.engine!=L"directory"&&o.engine!=L"mft")throw std::runtime_error("Unknown engine");
}
static Inventory scan(Options o){
 cleanOptions(o);Inventory inv;inv.started=timestamp();ULONGLONG start=GetTickCount64();
 for(const auto&root:o.roots){if(cancelScan.load())break;
  bool volume=root.size()==3&&root[1]==L':'&&root[2]==L'\\';wchar_t fs[40]{};bool ntfs=volume&&GetVolumeInformationW(root.c_str(),nullptr,0,nullptr,nullptr,nullptr,fs,40)&&_wcsicmp(fs,L"NTFS")==0;
  std::string reason;bool used=false;
  if(o.engine!=L"directory"&&ntfs&&isAdmin())used=scanMft(inv,o,root,reason);
  else if(o.engine==L"mft")reason="MFT requires a full NTFS volume and administrator access";
  if(!used){if(reason.empty())reason=volume?"No elevated NTFS access; native directory enumeration":"Selected folder: native buffered directory enumeration";inv.notes.push_back(utf8(root)+": "+reason);scanDirectory(inv,o,root);}
  inv.engines.push_back(utf8(root)+": "+(used?"MFT + buffered metadata":"Win32 buffered directory"));
 }
 inv.cancelled=cancelScan.load();
 for(auto&n:inv.nodes)if(n.dir){n.bytes=0;n.known=!inv.cancelled;}
 for(size_t i=inv.nodes.size();i-->0;){auto&n=inv.nodes[i];if(n.parent>=0){auto&p=inv.nodes[n.parent];if(n.dir||n.known)p.bytes+=n.bytes;if(!n.known||n.state!="ok")p.known=false;}}
 inv.seconds=(GetTickCount64()-start)/1000.0;inv.finished=timestamp();return inv;
}
static std::wstring fullPath(const Inventory& inv,int id){const auto&n=inv.nodes[id];return n.dir?inv.dirs[id]:join(inv.dirs[n.parent],n.name);}
static void saveReport(const Inventory& inv,const Options& o){
 const std::wstring tmp=o.output+L".tmp";HANDLE f=CreateFileW(extended(tmp).c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
 if(f==INVALID_HANDLE_VALUE)throw std::runtime_error("Cannot create temporary report (existing .tmp is preserved): "+utf8(errorText(GetLastError())));
 try{
  writeAll(f,REPORT_HEAD,sizeof(REPORT_HEAD)-1);
  writeAll(f,"{\"version\":\"0.1.0-test\",\"started\":"+json(inv.started)+",\"finished\":"+json(inv.finished)+",\"seconds\":"+std::to_string(inv.seconds)+",\"hidden\":"+(o.hidden?"true":"false")+",\"cancelled\":"+(inv.cancelled?"true":"false")+",\"errors\":"+std::to_string(inv.errors)+",\"skipped\":"+std::to_string(inv.skipped)+",\"hiddenSkipped\":"+std::to_string(inv.hiddenSkipped)+",\"engines\":[");
  for(size_t i=0;i<inv.engines.size();i++){if(i)writeAll(f,",");writeAll(f,js(inv.engines[i]));}writeAll(f,"],\"notes\":[");
  for(size_t i=0;i<inv.notes.size();i++){if(i)writeAll(f,",");writeAll(f,js(inv.notes[i]));}writeAll(f,"],\"nodes\":[");
  std::string buffer;buffer.reserve(1024*1024);
  for(size_t i=0;i<inv.nodes.size();i++){
   const auto&n=inv.nodes[i];if(i)buffer+=',';
   buffer+='['+std::to_string(n.parent)+','+json(n.name)+','+(n.dir?"true":"false")+',';
   // Directories retain known subtotal even when their completeness flag is false.
   buffer+=(!n.dir&&!n.known)?"null":'"'+std::to_string(n.bytes)+'"';buffer+=',';
   buffer+=n.created?json(timestamp(n.created)):"null";buffer+=',';buffer+=n.modified?json(timestamp(n.modified)):"null";
   buffer+=','+std::to_string(n.attrs)+','+js(n.state)+','+std::to_string(n.error)+','+(n.known?"true":"false")+']';
   if(buffer.size()>512*1024){writeAll(f,buffer);buffer.clear();}
  }
  writeAll(f,buffer);writeAll(f,"]}");writeAll(f,REPORT_TAIL,sizeof(REPORT_TAIL)-1);
  if(!FlushFileBuffers(f))throw std::runtime_error("Report flush failed");CloseHandle(f);f=INVALID_HANDLE_VALUE;
  if(!MoveFileExW(extended(tmp).c_str(),extended(o.output).c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw std::runtime_error("Cannot finalize report: "+utf8(errorText(GetLastError())));
 }catch(...){if(f!=INVALID_HANDLE_VALUE)CloseHandle(f);throw;}
}
static std::wstring editText(HWND h){int len=GetWindowTextLengthW(h);std::wstring s(len+1,L'\0');GetWindowTextW(h,s.data(),len+1);s.resize(len);return s;}
static void addRoots(Options& o,const std::wstring& text){size_t pos=0;while(pos<text.size()){size_t end=text.find(L'\n',pos);auto part=text.substr(pos,end==std::wstring::npos?end:end-pos);if(!part.empty()&&part.back()==L'\r')part.pop_back();if(!part.empty())o.roots.push_back(part);if(end==std::wstring::npos)break;pos=end+1;}}
static std::wstring defaultOutput(){wchar_t dir[32768];GetModuleFileNameW(nullptr,dir,32768);std::wstring base=dir;base=base.substr(0,base.find_last_of(L'\\'));SYSTEMTIME s;GetLocalTime(&s);wchar_t name[80];swprintf(name,80,L"DiskInventory-%04u%02u%02u-%02u%02u%02u.html",s.wYear,s.wMonth,s.wDay,s.wHour,s.wMinute,s.wSecond);return join(base,name);}
static DWORD WINAPI scanThread(void*){try{Inventory inv=scan(activeOptions);saveReport(inv,activeOptions);lastOutput=activeOptions.output;lastFailure.clear();}catch(const std::exception&e){lastFailure=e.what();}running=false;PostMessageW(mainWindow,WM_APP+1,0,0);return 0;}
static HWND control(const wchar_t* cls,const wchar_t* text,DWORD style,int x,int y,int w,int h,int id){HWND c=CreateWindowExW(cls==std::wstring(L"EDIT")?WS_EX_CLIENTEDGE:0,cls,text,WS_CHILD|WS_VISIBLE|style,x,y,w,h,mainWindow,(HMENU)(INT_PTR)id,GetModuleHandleW(nullptr),nullptr);SendMessageW(c,WM_SETFONT,(WPARAM)uiFont,TRUE);return c;}
static LRESULT CALLBACK windowProc(HWND h,UINT msg,WPARAM wp,LPARAM lp){
 if(msg==WM_CREATE){mainWindow=h;uiFont=CreateFontW(-16,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Microsoft YaHei UI");
  control(L"STATIC",L"磁盘文件清单  0.1 测试版",0,22,18,660,28,0);control(L"STATIC",L"扫描路径（每行一个，可填 C:\\ 或指定文件夹）",0,22,58,650,24,0);
  rootEdit=control(L"EDIT",L"",ES_MULTILINE|ES_AUTOVSCROLL|WS_VSCROLL|WS_TABSTOP,22,86,550,74,101);
  control(L"BUTTON",L"选择文件夹…",WS_TABSTOP,586,86,150,33,102);control(L"BUTTON",L"全部本地磁盘",WS_TABSTOP,586,126,150,33,103);
  hiddenCheck=control(L"BUTTON",L"包含隐藏文件和文件夹",BS_AUTOCHECKBOX|WS_TABSTOP,22,174,310,26,104);
  adminButton=control(L"BUTTON",isAdmin()?L"当前已是管理员":L"以管理员重启…",WS_TABSTOP,530,171,206,31,105);if(isAdmin())EnableWindow(adminButton,FALSE);
  control(L"STATIC",L"离线 HTML 输出位置",0,22,218,600,23,0);outEdit=control(L"EDIT",defaultOutput().c_str(),ES_AUTOHSCROLL|WS_TABSTOP,22,246,550,29,106);control(L"BUTTON",L"另存为…",WS_TABSTOP,586,245,150,31,107);
  scanButton=control(L"BUTTON",L"开始扫描并生成报告",WS_TABSTOP|BS_DEFPUSHBUTTON,22,295,228,38,108);cancelButton=control(L"BUTTON",L"取消扫描",WS_TABSTOP,264,295,130,38,109);EnableWindow(cancelButton,FALSE);openButton=control(L"BUTTON",L"打开报告",WS_TABSTOP,408,295,130,38,110);EnableWindow(openButton,FALSE);
  statusText=control(L"STATIC",L"请选择路径。仅采集元数据，不读取文件正文。",0,22,350,714,45,111);SetTimer(h,1,250,nullptr);return 0;
 }
 if(msg==WM_TIMER&&running){auto s=L"扫描中："+std::to_wstring(progressFiles.load())+L" 个文件，"+std::to_wstring(progressDirs.load())+L" 个文件夹。取消后仍会保存部分报告。";SetWindowTextW(statusText,s.c_str());return 0;}
 if(msg==WM_APP+1){EnableWindow(scanButton,TRUE);EnableWindow(rootEdit,TRUE);EnableWindow(outEdit,TRUE);EnableWindow(hiddenCheck,TRUE);EnableWindow(cancelButton,FALSE);EnableWindow(openButton,lastFailure.empty());if(lastFailure.empty()){SetWindowTextW(statusText,(L"报告已生成："+lastOutput).c_str());}else{SetWindowTextW(statusText,L"生成失败；详细信息见提示。");MessageBoxW(h,wide(lastFailure).c_str(),L"扫描或写入失败",MB_OK|MB_ICONERROR);}return 0;}
 if(msg==WM_COMMAND){int id=LOWORD(wp);
  if(running&&id!=109)return 0;
  if(id==102){BROWSEINFOW bi{};bi.hwndOwner=h;bi.lpszTitle=L"选择扫描文件夹或磁盘";bi.ulFlags=BIF_RETURNONLYFSDIRS|BIF_NEWDIALOGSTYLE;PIDLIST_ABSOLUTE pid=SHBrowseForFolderW(&bi);if(pid){wchar_t path[32768];if(SHGetPathFromIDListW(pid,path))SetWindowTextW(rootEdit,path);CoTaskMemFree(pid);}}
  if(id==103){std::wstring roots;DWORD bits=GetLogicalDrives();for(int i=0;i<26;i++)if(bits&(1u<<i)){std::wstring p;p+=wchar_t(L'A'+i);p+=L":\\";if(GetDriveTypeW(p.c_str())==DRIVE_FIXED){if(!roots.empty())roots+=L"\r\n";roots+=p;}}SetWindowTextW(rootEdit,roots.c_str());}
  if(id==105){std::wstring exe(32768,L'\0');exe.resize(GetModuleFileNameW(nullptr,exe.data(),(DWORD)exe.size()));std::wstring args=L"--gui";Options saved;addRoots(saved,editText(rootEdit));for(const auto&r:saved.roots)args+=L" --root \""+r+(r.back()==L'\\'?L"\\":L"")+L"\"";args+=L" --output \""+editText(outEdit)+L"\"";if(SendMessageW(hiddenCheck,BM_GETCHECK,0,0)==BST_CHECKED)args+=L" --include-hidden";auto result=(INT_PTR)ShellExecuteW(h,L"runas",exe.c_str(),args.c_str(),nullptr,SW_SHOWNORMAL);if(result>32)DestroyWindow(h);else SetWindowTextW(statusText,L"未提权，仍可直接开始普通扫描。");}
  if(id==107){wchar_t path[32768]{};auto text=editText(outEdit);wcsncpy(path,text.c_str(),32767);OPENFILENAMEW of{};of.lStructSize=sizeof(of);of.hwndOwner=h;of.lpstrFilter=L"离线 HTML 报告\0*.html\0\0";of.lpstrFile=path;of.nMaxFile=32768;of.lpstrDefExt=L"html";of.Flags=OFN_OVERWRITEPROMPT|OFN_NOCHANGEDIR;if(GetSaveFileNameW(&of))SetWindowTextW(outEdit,path);}
  if(id==108){try{activeOptions=Options{};addRoots(activeOptions,editText(rootEdit));activeOptions.output=editText(outEdit);activeOptions.hidden=SendMessageW(hiddenCheck,BM_GETCHECK,0,0)==BST_CHECKED;cleanOptions(activeOptions);if(GetFileAttributesW(extended(activeOptions.output).c_str())!=INVALID_FILE_ATTRIBUTES&&MessageBoxW(h,L"输出报告已经存在，是否覆盖？",L"覆盖报告",MB_YESNO|MB_ICONQUESTION)!=IDYES)return 0;cancelScan=false;progressFiles=0;progressDirs=0;running=true;EnableWindow(scanButton,FALSE);EnableWindow(openButton,FALSE);EnableWindow(rootEdit,FALSE);EnableWindow(outEdit,FALSE);EnableWindow(hiddenCheck,FALSE);EnableWindow(cancelButton,TRUE);HANDLE worker=CreateThread(nullptr,0,scanThread,nullptr,0,nullptr);if(worker)CloseHandle(worker);else{running=false;throw std::runtime_error("Cannot start scan thread");}}catch(const std::exception&e){MessageBoxW(h,wide(e.what()).c_str(),L"无法开始",MB_OK|MB_ICONERROR);}}
  if(id==109){cancelScan=true;SetWindowTextW(statusText,L"正在停止扫描并保存部分报告…");}
  if(id==110&&!lastOutput.empty())ShellExecuteW(h,L"open",lastOutput.c_str(),nullptr,nullptr,SW_SHOWNORMAL);return 0;
 }
 if(msg==WM_CLOSE){if(running){cancelScan=true;SetWindowTextW(statusText,L"请等待部分报告保存完成后再关闭。");return 0;}DestroyWindow(h);return 0;}
 if(msg==WM_DESTROY){KillTimer(h,1);if(uiFont)DeleteObject(uiFont);PostQuitMessage(0);return 0;}return DefWindowProcW(h,msg,wp,lp);
}
static void logLine(const std::wstring&s){HANDLE h=GetStdHandle(STD_OUTPUT_HANDLE);if(h&&h!=INVALID_HANDLE_VALUE){DWORD n;auto a=utf8(s+L"\r\n");WriteFile(h,a.data(),(DWORD)a.size(),&n,nullptr);}}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,PWSTR,int show){
 SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOOPENFILEERRORBOX);int argc=0;LPWSTR* argv=CommandLineToArgvW(GetCommandLineW(),&argc);Options o;o.output=defaultOutput();bool gui=argc==1;
 try{
  for(int i=1;i<argc;i++){std::wstring a=argv[i];if(a==L"--gui")gui=true;else if(a==L"--include-hidden")o.hidden=true;else if((a==L"--root"||a==L"--output"||a==L"--engine")&&i+1<argc){auto value=std::wstring(argv[++i]);if(a==L"--root")o.roots.push_back(value);else if(a==L"--output")o.output=value;else o.engine=value;}else if(a==L"--help"){AttachConsole(ATTACH_PARENT_PROCESS);logLine(L"DiskInventory --root PATH [--root PATH] --output FILE.html [--include-hidden] [--engine auto|directory|mft] [--gui]");LocalFree(argv);return 0;}else throw std::runtime_error("Unknown or incomplete argument: "+utf8(a));}
  LocalFree(argv);argv=nullptr;
  if(!gui){AttachConsole(ATTACH_PARENT_PROCESS);cleanOptions(o);auto inv=scan(o);saveReport(inv,o);logLine(L"Report: "+o.output+L"; files="+std::to_wstring(inv.files)+L"; directories="+std::to_wstring(inv.folders));return inv.cancelled?3:inv.errors?2:0;}
  CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);SetProcessDPIAware();WNDCLASSW wc{};wc.lpfnWndProc=windowProc;wc.hInstance=instance;wc.lpszClassName=L"DiskInventoryWindow";wc.hCursor=LoadCursorW(nullptr,IDC_ARROW);wc.hbrBackground=(HBRUSH)(COLOR_WINDOW+1);RegisterClassW(&wc);
  HWND win=CreateWindowExW(0,wc.lpszClassName,L"磁盘文件清单 · 离线 HTML 扫描器",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU|WS_MINIMIZEBOX,CW_USEDEFAULT,CW_USEDEFAULT,780,455,nullptr,nullptr,instance,nullptr);
  if(!win)throw std::runtime_error("Cannot create window");if(!o.roots.empty()){std::wstring roots;for(auto&r:o.roots){if(!roots.empty())roots+=L"\r\n";roots+=r;}SetWindowTextW(rootEdit,roots.c_str());}SetWindowTextW(outEdit,o.output.c_str());if(o.hidden)SendMessageW(hiddenCheck,BM_SETCHECK,BST_CHECKED,0);ShowWindow(win,show);MSG msg;while(GetMessageW(&msg,nullptr,0,0)>0){if(!IsDialogMessageW(win,&msg)){TranslateMessage(&msg);DispatchMessageW(&msg);}}CoUninitialize();return 0;
 }catch(const std::exception&e){if(argv)LocalFree(argv);AttachConsole(ATTACH_PARENT_PROCESS);logLine(L"Error: "+wide(e.what()));if(gui)MessageBoxW(nullptr,wide(e.what()).c_str(),L"错误",MB_OK|MB_ICONERROR);return 1;}
}
