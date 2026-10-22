---
nombre: autenticacion
palabras: autenticación, autenticacion, login, contraseña, contrasena, password, sesión, sesion, usuario
---
- Nunca guardar contraseñas en texto plano: usar hash con sal (hashlib.scrypt o pbkdf2_hmac).
- Comparar hashes con hmac.compare_digest, no con ==.
- No hardcodear secretos; leerlos de variables de entorno.
- Mensajes de error genéricos ("credenciales inválidas"), sin revelar si falló el usuario o la clave.
- Limitar intentos fallidos.
