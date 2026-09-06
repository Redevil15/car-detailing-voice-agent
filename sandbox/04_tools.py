from datetime import date, timedelta

from mcp_server.tools import checar_disponibilidad, consultar_precio, registrar_servicio

print("1. Nombre exacto con acentos:")
print("  ", consultar_precio("Lavado básico"))

print("\n2. Sin acentos ni mayúsculas (como llega del STT):")
print("  ", consultar_precio("LAVADO BASICO"))

print("\n3. Ambiguo — debe devolver encontrado=False con candidatos:")
print("  ", consultar_precio("lavado"))

print("\n4. Inexistente — devuelve el catálogo completo:")
print("  ", consultar_precio("cambio de aceite"))

manana = (date.today() + timedelta(days=1)).isoformat()
print(f"\n5. Disponibilidad de {manana}:")
print("  ", checar_disponibilidad(manana))

print("\n6. Fecha basura:")
print("  ", checar_disponibilidad("el sábado"))

print("\n7. Registro de una cita:")
disp = checar_disponibilidad(manana)
if disp.horas_libres:
    print("  ", registrar_servicio(
        cliente="Cliente De Prueba",
        telefono="5599999999",
        servicio="Encerado",
        fecha=manana,
        hora=disp.horas_libres[0],
    ))

print("\n8. Registro con servicio ambiguo — debe fallar limpiamente:")
print("  ", registrar_servicio(
    cliente="Cliente De Prueba", telefono="5599999999",
    servicio="lavado", fecha=manana, hora="09:00",
))
