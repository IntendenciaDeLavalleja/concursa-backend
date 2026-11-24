from flask import jsonify, render_template, request


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({
                'message': 'Recurso no encontrado.',
                'status': 404,
            }), 404

        return render_template('errors/404.html'), 404
