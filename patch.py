import os

def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ Filen saknas: {path}")
        return None

def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Uppdaterade {path}")

def patch_modbus_private_h():
    path = os.path.join("src", "libmodbus", "modbus-private.h")
    content = read_file(path)
    if not content: return

    # Lägg till funktionspekaren i struct _modbus
    if "int (*request_callback)" in content:
        print(f"⚠️ {path} verkar redan ha request_callback.")
    else:
        # Vi letar efter slutet på structen, men innan };
        # Ett säkert ställe att lägga det är efter 'void *backend_data;' om det finns
        if "void *backend_data;" in content:
            replacement = "void *backend_data;\n    int (*request_callback)(modbus_t *ctx, uint8_t *req, int req_length);"
            new_content = content.replace("void *backend_data;", replacement)
            write_file(path, new_content)
        else:
            print(f"❌ Kunde inte hitta 'void *backend_data;' i {path}. Patchen misslyckades för denna fil.")

def patch_modbus_h():
    path = os.path.join("src", "libmodbus", "modbus.h")
    content = read_file(path)
    if not content: return

    if "modbus_set_request_callback" in content:
        print(f"⚠️ {path} verkar redan ha modbus_set_request_callback.")
    else:
        # Lägg till deklarationen i slutet, t.ex. efter modbus_set_response_timeout
        anchor = "int modbus_set_response_timeout(modbus_t *ctx, uint32_t to_sec, uint32_t to_usec);"
        if anchor in content:
            insertion = f"\n{anchor}\nvoid modbus_set_request_callback(modbus_t *ctx, int (*callback)(modbus_t *ctx, uint8_t *req, int req_length));"
            new_content = content.replace(anchor, insertion)
            write_file(path, new_content)
        else:
             # Fallback: Försök hitta en annan säker funktion
             anchor = "MODBUS_BEGIN_DECLS"
             if anchor in content:
                 insertion = f"{anchor}\n\nvoid modbus_set_request_callback(modbus_t *ctx, int (*callback)(modbus_t *ctx, uint8_t *req, int req_length));"
                 new_content = content.replace(anchor, insertion)
                 write_file(path, new_content)
             else:
                print(f"❌ Kunde inte hitta en bra plats att infoga deklarationen i {path}.")

def patch_modbus_c():
    path = os.path.join("src", "libmodbus", "modbus.c")
    content = read_file(path)
    if not content: return

    # 1. Initiera till NULL i _modbus_init_common
    if "ctx->request_callback = NULL;" not in content:
        anchor = "ctx->error_recovery = MODBUS_ERROR_RECOVERY_NONE;"
        if anchor in content:
            new_content = content.replace(anchor, f"{anchor}\n    ctx->request_callback = NULL;")
            content = new_content
            write_file(path, content) # Spara stegvis för säkerhets skull
        else:
            print(f"❌ Kunde inte hitta initieringsplatsen i {path}")

    # 2. Lägg till implementeringen av settern
    if "void modbus_set_request_callback" not in content:
        # Lägg till sist i filen eller före en annan funktion.
        # Vi lägger den före modbus_connect
        anchor = "int modbus_connect(modbus_t *ctx)"
        if anchor in content:
            func_impl = """
void modbus_set_request_callback(modbus_t *ctx, int (*callback)(modbus_t *ctx, uint8_t *req, int req_length)) {
    ctx->request_callback = callback;
}

"""
            new_content = content.replace(anchor, func_impl + anchor)
            content = new_content
            write_file(path, content)

    # 3. Anropa callbacken i modbus_reply
    if "ctx->request_callback(ctx" not in content:
        # Hitta modbus_reply funktionen och infoga anropet tidigt
        # Vi letar efter felkollen i början av funktionen
        anchor_check = "if (ctx == NULL || req == NULL || req_length <= 0 || mb_mapping == NULL) {"
        # Vi måste hitta slutet på denna if-sats. Det är svårt med regex.
        # Så vi letar efter raden "return -1;" inuti den och } efteråt.
        
        # Enklare metod: Hitta offset-beräkningen som kommer efteråt.
        anchor_logic = "offset = ctx->backend->header_length;"
        
        if anchor_logic in content:
            callback_call = """
    if (ctx->request_callback != NULL) {
        ctx->request_callback(ctx, (uint8_t*)req, req_length);
    }

    """
            new_content = content.replace(anchor_logic, callback_call + anchor_logic)
            write_file(path, new_content)
        else:
            print(f"❌ Kunde inte hitta platsen att infoga callback-anropet i modbus_reply i {path}")

def patch_modbus_server_h():
    path = os.path.join("src", "ModbusServer.h")
    content = read_file(path)
    if not content: return

    if "void onRequest(" in content:
        print(f"⚠️ {path} verkar redan ha onRequest.")
        return

    # Lägg till i public-sektionen
    anchor = "virtual void poll();"
    if anchor in content:
        insertion = """virtual void poll();

  void onRequest(void (*callback)(int slave, int function, int address, int quantity));
  static void (*_onRequestCallback)(int slave, int function, int address, int quantity);
"""
        new_content = content.replace(anchor, insertion)
        write_file(path, new_content)
    else:
        print(f"❌ Kunde inte hitta 'virtual void poll();' i {path}")

def patch_modbus_server_cpp():
    path = os.path.join("src", "ModbusServer.cpp")
    content = read_file(path)
    if not content: return

    if "internalRequestCallback" in content:
        print(f"⚠️ {path} verkar redan vara patchad.")
        return

    # 1. Lägg till statiska variabler och hjälpfunktionen högst upp (efter includes)
    anchor_include = '#include "ModbusServer.h"'
    if anchor_include in content:
        insertion = """#include "ModbusServer.h"

// Define the static member
void (*ModbusServer::_onRequestCallback)(int, int, int, int) = NULL;

extern "C" {
// Helper callback for libmodbus
int internalRequestCallback(modbus_t *ctx, uint8_t *req, int req_length) {
    if (ModbusServer::_onRequestCallback) {
        int header_length = modbus_get_header_length(ctx);
        if (req_length < header_length + 1) return 0;

        int slave = req[header_length - 1];
        int function = req[header_length];
        int address = 0;
        int quantity = 0;

        // Extract address (usually 2 bytes after function)
        if (req_length >= header_length + 3) {
            address = (req[header_length + 1] << 8) + req[header_length + 2];
        }

        // Extract quantity based on function type
        switch(function) {
            case MODBUS_FC_READ_COILS:
            case MODBUS_FC_READ_DISCRETE_INPUTS:
            case MODBUS_FC_READ_HOLDING_REGISTERS:
            case MODBUS_FC_READ_INPUT_REGISTERS:
            case MODBUS_FC_WRITE_MULTIPLE_COILS:
            case MODBUS_FC_WRITE_MULTIPLE_REGISTERS:
                if (req_length >= header_length + 5) {
                    quantity = (req[header_length + 3] << 8) + req[header_length + 4];
                }
                break;
            case MODBUS_FC_WRITE_SINGLE_COIL:
            case MODBUS_FC_WRITE_SINGLE_REGISTER:
                quantity = 1; 
                break;
            default:
                quantity = 0;
        }

        ModbusServer::_onRequestCallback(slave, function, address, quantity);
    }
    return 0;
}
}
"""
        # Ersätt bara include med include + koden (men undvik duplicering om man kör scriptet igen)
        # Vi kollar en gång till för säkerhets skull
        if "internalRequestCallback" not in content:
             new_content = content.replace(anchor_include, insertion)
             content = new_content
             write_file(path, content)

    # 2. Implementera onRequest metoden
    if "void ModbusServer::onRequest" not in content:
        anchor_destructor = "ModbusServer::~ModbusServer()\n{"
        # Hitta slutet på destruktorn
        destructor_end_idx = content.find("}", content.find(anchor_destructor))
        if destructor_end_idx != -1:
            insertion = """

void ModbusServer::onRequest(void (*callback)(int, int, int, int)) {
    _onRequestCallback = callback;
}
"""
            # Infoga efter destruktorn
            new_content = content[:destructor_end_idx+1] + insertion + content[destructor_end_idx+1:]
            content = new_content
            write_file(path, content)

    # 3. Registrera callbacken i begin()
    if "modbus_set_request_callback" not in content:
        anchor_slave = "modbus_set_slave(_modbus, slaveId);"
        if anchor_slave in content:
            replacement = "modbus_set_slave(_modbus, slaveId);\n    modbus_set_request_callback(_modbus, internalRequestCallback);"
            new_content = content.replace(anchor_slave, replacement)
            write_file(path, new_content)
        else:
            print(f"❌ Kunde inte hitta 'modbus_set_slave' i {path} för att registrera callbacken.")

def main():
    print("🚀 Startar robust patchning av ArduinoModbus...")
    
    if not os.path.exists("src/libmodbus"):
        print("❌ Hittar inte src/libmodbus. Se till att du står i roten av biblioteket.")
        return

    try:
        patch_modbus_private_h()
        patch_modbus_h()
        patch_modbus_c()
        patch_modbus_server_h()
        patch_modbus_server_cpp()
        print("\n🎉 Patchning slutförd! Kontrollera eventuella felmeddelanden ovan.")
    except Exception as e:
        print(f"\n❌ Ett oväntat fel inträffade: {e}")

if __name__ == "__main__":
    main()