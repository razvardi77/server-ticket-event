"""Application-level errors for the EvenTicket server.
 
Raise ApiError anywhere in the impl layer, e.g.:
    raise ApiError(404, "SHOWING_NOT_FOUND", f"No showing with id '{showing_id}'.")
 
The handler turns it into a JSON response that matches the
`Error` model from the OpenAPI spec: {"code": ..., "message": ...}
"""
 
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
 
 
class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
 
 
def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
 