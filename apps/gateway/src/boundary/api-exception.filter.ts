import { ArgumentsHost, Catch, ExceptionFilter, HttpException, HttpStatus } from "@nestjs/common";
import type { Response, Request } from "express";
import { randomUUID } from "node:crypto";
@Catch()
export class ApiExceptionFilter implements ExceptionFilter{
  catch(exception:unknown,host:ArgumentsHost){const ctx=host.switchToHttp();const req=ctx.getRequest<Request>();const res=ctx.getResponse<Response>();const status=exception instanceof HttpException?exception.getStatus():HttpStatus.INTERNAL_SERVER_ERROR;const raw=exception instanceof HttpException?exception.getResponse():null;const obj=typeof raw==="object"&&raw!==null?raw as Record<string,unknown>:{};const correlation=String(req.headers["x-correlation-id"]??randomUUID());res.status(status).json({error:{code:String(obj.code??(status===500?"INTERNAL_ERROR":"REQUEST_FAILED")),message:String(obj.message??raw??"Request failed"),status,correlation_id:correlation,details:obj.details??null}});}
}
